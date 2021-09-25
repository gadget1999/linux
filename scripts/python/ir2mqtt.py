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
from common import Logger, ExitSignal, CLIParser
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

  def connect(self, device_id):
    # Clean up first if not yet
    self.disconnect()
    # device id in format of 80ee:0a21
    parts = device_id.split(':')
    vendor = int(parts[0], 16)
    prod_id = int(parts[1], 16)
    # Connect to device
    self.__vendor = vendor
    self.__prod_id = prod_id
    self.__device = usb.core.find(idVendor=vendor, idProduct=prod_id)
    if not self.is_connected():
      raise Exception(f"Cannot find device: {device_id}")
    # Take control from the kernel
    self.__claim_device()
    logger.info(f"Device {device_id} connected.")

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
      self.__load_mapping(os.environ['IR2MQTT_MAPPING'].strip('\" '))
      self.__mqtt_server = os.environ['MQTT_SERVER'].strip('\" ')
      self.__mqtt_port = int(os.environ['MQTT_PORT'].strip('\" '))
      mqtt_user = os.environ['MQTT_USER'].strip('\" ')
      mqtt_password = os.environ['MQTT_PASSWORD'].strip('\" ')
      self.__mqtt_client = mqtt_client.Client("IR_MQTT_Bridge")
      self.__mqtt_client.on_connect = IR_MQTT_Bridge.__on_mqtt_connect
      self.__mqtt_client.on_disconnect = IR_MQTT_Bridge.__on_mqtt_disconnect
      self.__mqtt_client.on_publish = IR_MQTT_Bridge.__on_mqtt_publish
      if mqtt_user or mqtt_password:
        self.__mqtt_client.username_pw_set(mqtt_user, mqtt_password)
    except Exception as e:
      logger.error(f"MQTT configuration is invalid: {e}")
      raise

  def __load_mapping(self, mapping_file):
    import json
    with open(mapping_file) as f:
      self.__mapping = json.load(f)
    # verify if mapping is correct
    for key in self.__mapping.keys():
      topic = self.__mapping[key]['topic']
      msg = self.__mapping[key]['msg']
      if not topic or not msg:
        raise Exception(f"Invalid mapping for: key={key}")

  def __on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
      client.connected_flag = True
      client.bad_connection_flag = False
      logger.info("MQTT client connected.")
    else:
      client.connected_flag = False
      client.bad_connection_flag = True
      logger.error(f"MQTT client connection error: {rc}")

  def __on_mqtt_disconnect(client, userdata, rc):
    logger.error(f"MQTT connection dropped: {rc}")
    client.connected_flag = False
    client.disconnect_flag = True

  def __on_mqtt_publish(client, userdata, mid):
    logger.info(f"Sent MQTT msg #{mid}")

  def __disconnect(self):
    self.__mqtt_client.loop_stop()
    self.__mqtt_client.disconnect()

  def __connect(self):
    if self.__mqtt_client.is_connected(): return
    self.__disconnect()
    logger.info("Connecting to MQTT server ...")
    self.__mqtt_client.connect(self.__mqtt_server, self.__mqtt_port)
    self.__mqtt_client.loop_start()

  def __process_key(self, key):
    try:
      self.__connect()
      # find MQTT mapping for key
      if key not in self.__mapping.keys():
        return
      topic = self.__mapping[key]['topic']
      message = self.__mapping[key]['msg']
      logger.info(f"MQTT cmd: {topic} {message}")
      self.__mqtt_client.publish(topic, message)
    except Exception as e:
      logger.error(f"Send \'{message}\' to topic \'{topic}\' failed: {e}")

  def start_monitor(self, device_id):
    keyboard = USB_Keyboard()
    try:
      keyboard.connect(device_id)
      # Loop data read until interrupt
      while True:
        try:
          key = keyboard.read_key()
          if not key:     continue
          if key == 20:   break # 'q' to stop
          logger.info(f"Key: {key}")
          self.__process_key(str(key))
        except Exception as e:
          logger.error(f"Exception: {e}")
    finally:
      keyboard.disconnect()
      self.__disconnect()

########################################
# CLI interface
########################################

def start_bridge(args):
  bridge = IR_MQTT_Bridge()
  bridge.start_monitor(args.device)

#################################
# Program starts
#################################
if (__name__ == '__main__'):
  CLI_config = { 'func':start_bridge, 'arguments': [
    {'name':'device', 'help':'USB device id (e.g., 80ee:0a21)'}
    ]}
  CLIParser.run(CLI_config)
