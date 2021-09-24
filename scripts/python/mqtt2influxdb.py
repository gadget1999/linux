#!/usr/bin/env python3

from logging import log
import os, sys, time
# for receiving MQTT messages
from paho.mqtt import client as mqtt_client
# for publishing InfluxDB data
from influxdb import InfluxDBHelper
# logging
from common import Logger, ExitSignal
logger = Logger.getLogger()

SLEEP_INTERVAL = 30  # (seconds) How often we check the core temperature.

INFLUXDB_TOPIC = "Monitor"
INFLUXDB_HOST = "MQTT2InfluxBridge"

class MQTT_Helper:
  def __init__(self, server, port, user, password, ID):
    try:
      self.__mqtt_server = server
      self.__mqtt_port = port
      self.__mqtt_client = mqtt_client.Client(ID)
      self.__mqtt_client.on_connect = MQTT_Helper.__on_mqtt_connect
      self.__mqtt_client.on_disconnect = MQTT_Helper.__on_mqtt_disconnect
      self.__mqtt_client.on_publish = MQTT_Helper.__on_mqtt_publish
      self.__mqtt_client.on_subscribe = MQTT_Helper.__on_mqtt_subscribe
      if user or password:
        self.__mqtt_client.username_pw_set(user, password)
    except Exception as e:
      logger.error(f"MQTT configuration is invalid: {e}")
      raise

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

  def __on_mqtt_subscribe(client, userdata, mid, granted_qos):
    logger.debug(f"Subscribe MQTT returned #{mid}")

  def __disconnect(self):
    self.__mqtt_client.loop_stop()
    self.__mqtt_client.disconnect()

  def __connect(self):
    if self.__mqtt_client.is_connected():
      return
    self.__disconnect()
    logger.info(f"Connecting to MQTT server {self.__mqtt_server}:{self.__mqtt_port}...")
    self.__mqtt_client.connect(self.__mqtt_server, self.__mqtt_port)

  def publish(self, topic, message):
    self.__connect()
    logger.info(f"Publishing MQTT topic:{topic} ({message})")
    self.__mqtt_client.publish(topic, message)

  def subscribe(self, topic, callback):
    self.__connect()
    logger.info(f"Subscribing to MQTT topic: {topic}")
    self.__mqtt_client.subscribe(topic)
    self.__mqtt_client.on_message = callback
    self.__mqtt_client.loop_forever()

class MQTT_InfluxDB_Bridge:
  ############ Class Level ##################
  def __on_mqtt_message(client, userdata, message):
    logger.debug(f"[get] Topic:{message.topic}, Data:{message.payload}")

  ############ Instance Level ##################
  def __init__(self):
    try:
      mqtt_server = os.environ['MQTT_SERVER'].strip('\" ')
      mqtt_port = int(os.environ['MQTT_PORT'].strip('\" '))
      mqtt_user = os.environ['MQTT_USER'].strip('\" ')
      mqtt_password = os.environ['MQTT_PASSWORD'].strip('\" ')
      self.__mqtt_helper = MQTT_Helper(mqtt_server, mqtt_port, mqtt_user, mqtt_password, INFLUXDB_HOST)
    except Exception as e:
      logger.error(f"Failed to initialize MQTT-InfluxDB Bridge: {e}")
      raise

  def run(self):
    try:
      self.__mqtt_helper.subscribe("basement/#", MQTT_InfluxDB_Bridge.__on_mqtt_message)
    except Exception as e:
      logger.error(f"MQTT2InfluxDB main function failed: {e}")

#################################
# Program starts
#################################

if (__name__ == '__main__'):
  ExitSignal.register()

  try:
    bridge = MQTT_InfluxDB_Bridge()
    bridge.run()
  except Exception as e:
    logger.error(f"Exception: {e}")
