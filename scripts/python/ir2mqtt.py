#!/usr/bin/env python3

''' Utility class to read from IR remote keyboard (e.g., Flirc)
  and forward events to mqtt to control wifi enabled devices
'''

import os, sys, time
# for reading USB interface
import usb.core
import usb.util
# for sending MQTT messages
from paho.mqtt import client as mqtt_client
# logging
from common import Logger, CLIParser
logger = Logger.getLogger()

class USB_Keyboard:
  def __init__(self):
    self.__vendor = None    # Device vendor ID
    self.__prod_id = None   # Device product ID
    self.__device = None    # A usb.core device object placeholder
    self.__endpoint = None  # A usb.core device attribute placeholder
    self.__interface = 0  # Device constant
    self.__detached_kernel = False

  def __claim_device(self):
    if not self.is_connected:
      raise Exception(f"Device [{hex(vendor)}:{hex(prod_id)}] not connected.")
     # Set endpoint
    self.__endpoint = self.__device[0][(0, 0)][0]
    # If the device is being used by the kernel
    if (self.__device.is_kernel_driver_active(self.__interface)) is True:
      logger.info("Detaching kernel driver...")
      self.__device.detach_kernel_driver(self.__interface)
      self.__detached_kernel = True
    # Claim the device
    logger.info("Claiming device interface...")
    usb.util.claim_interface(self.__device, self.__interface)

  def is_connected(self):
    return (self.__device and self.__prod_id and self.__vendor)

  def connect(self, vendor, prod_id):
    # Clean up first if not yet
    self.disconnect()
    # Connect to device
    self.__vendor = vendor
    self.__prod_id = prod_id
    self.__device = usb.core.find(idVendor=vendor, idProduct=prod_id)
    if not self.is_connected():
      raise Exception(f"Cannot find device: {hex(vendor)}:{hex(prod_id)}")
    # Take control from the kernel
    self.__claim_device()
    logger.info(f"Device {hex(vendor)}:{hex(prod_id)} connected.")

  def disconnect(self):
    if self.is_connected():
      # Release device
      logger.info("Release device interface.")
      usb.util.release_interface(self.__device, self.__interface)
      if (self.__detached_kernel):
        logger.info("Re-attach kernel driver.")
        self.__device.attach_kernel_driver(self.__interface)
    # Reinitialize for reuse
    self.__init__()

  def read_key(self, timeout=300000):
    # Check for connected device
    if not self.is_connected:
      raise Exception(f"Device not connected.")
    # return key if succeeded, otherwise None if timed out
    try:
      data = self.__device.read(self.__endpoint.bEndpointAddress,
                  self.__endpoint.wMaxPacketSize, timeout)
      # typical output is a pair of something like:
      #  ('B', [0, 0, 38, 0, 0, 0, 0, 0])
      #  ('B', [0, 0, 0, 0, 0, 0, 0, 0])
      key = data[2]
      if (key != 0):
        return key
      else:
        return None
    except usb.core.USBTimeoutError:
      return None

class IR_MQTT_Bridge:
  def __init__(self):
    try:
      self.__mqtt_server = os.environ['MQTT_SERVER'].strip('\" ')
      self.__mqtt_port = int(os.environ['MQTT_PORT'].strip('\" '))
      mqtt_user = os.environ['MQTT_USER'].strip('\" ')
      mqtt_password = os.environ['MQTT_PASSWORD'].strip('\" ')
      self.__mqtt_client = mqtt_client.Client("IR_MQTT_Bridge")
      self.__mqtt_client.on_connect = IR_MQTT_Bridge.on_mqtt_connect
      self.__mqtt_client.on_disconnect = IR_MQTT_Bridge.on_mqtt_disconnect
      if mqtt_user or mqtt_password:
        self.__mqtt_client.username_pw_set(mqtt_user, mqtt_password)
    except Exception as e:
      logger.error(f"MQTT configuration is invalid: {e}")
      raise

  def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
      client.connected_flag = True
      client.bad_connection_flag = False
      logger.info("MQTT client connected.")
    else:
      client.connected_flag = False
      client.bad_connection_flag = True
      logger.error(f"MQTT client connection error: {rc}")

  def on_mqtt_disconnect(client, userdata, rc):
    logger.error(f"MQTT connection dropped: {rc}")
    client.connected_flag = False
    client.disconnect_flag = True

  def __disconnect(self):
    self.__mqtt_client.loop_stop()
    self.__mqtt_client.disconnect()

  def __connect(self):
    if self.__mqtt_client.is_connected(): return
    self.__disconnect()
    logger.info("Connecting to MQTT server ...")
    self.__mqtt_client.connect(self.__mqtt_server, self.__mqtt_port)
    self.__mqtt_client.loop_start()

  def __post_mqtt_message(self, topic, message):
    try:
      self.__connect()
      result = self.__mqtt_client.publish(topic, message)
      # result: [0, 1]
      status = result[0]
      if status != 0:
        logger.error(f"Send \'{message}\' to topic \'{topic}\' failed.")
    except Exception as e:
      logger.error(f"Send \'{message}\' to topic \'{topic}\' failed: {e}")

  def start_monitor(self, vendor_id, prod_id, mqtt_bridge_topic):
    keyboard = USB_Keyboard()
    try:
      keyboard.connect(vendor_id, prod_id)
      # Loop data read until interrupt
      while True:
        try:
          key = keyboard.read_key()
          if not key: continue
          logger.info(f"Key: {key}")
          self.__post_mqtt_message(mqtt_bridge_topic, str(key))
        except Exception as e:
          logger.error(f"Exception: {e}")
    finally:
      keyboard.disconnect()
      self.__disconnect()

########################################
# CLI interface
########################################

def start_bridge(args):
  # device id in format of 80ee:0a21
  parts = args.device.split(':')
  vendor = int(parts[0], 16)
  product = int(parts[1], 16)
  MQTT_TOPIC = "IR2MQTTBridge"
  bridge = IR_MQTT_Bridge()
  bridge.start_monitor(vendor, product, MQTT_TOPIC)

#################################
# Program starts
#################################
def handler(signal_received, frame):
  logger.critical("Terminate signal is captured, exiting...")
  sys.exit(2)

if (__name__ == '__main__'):
  # for capturing Kill signal
  from signal import signal, SIGTERM
  signal(SIGTERM, handler)

  CLI_config = { 'func':start_bridge, 'arguments': [
    {'name':'device', 'help':'USB device id (e.g., 80ee:0a21)'}
    ]}
  try:
    parser = CLIParser.get_parser(CLI_config)
    CLIParser.run(parser)
  except Exception as e:
    logger.error(f"Exception happened: {e}")
    sys.exit(1)
