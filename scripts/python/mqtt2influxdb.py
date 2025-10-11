#!/usr/bin/env python3

from logging import log
import os, sys, time
# for receiving MQTT messages
from paho.mqtt import client as mqtt_client
# for publishing InfluxDB data
from influxdb import InfluxDBConfig, InfluxDBHelper
# for struct-like class
import copy
from dataclasses import dataclass
# config, CLI and logging
import configparser
from common import Logger, CLIParser
logger = Logger.getLogger()

INFLUXDB_CATEGORY = "Metrics"

@dataclass
class MQTTSettings:
  server: str = None
  port: int = 1883
  user: str = None
  password: str = None
  client_id: str = None

class MQTT_Helper:
  def __init__(self, settings):
    try:
      self.__mqtt_server = settings.server
      self.__mqtt_port = settings.port
      mqtt_API_version = mqtt_client.CallbackAPIVersion.VERSION2
      self.__mqtt_client = mqtt_client.Client(mqtt_API_version, settings.client_id, clean_session=False)
      self.__mqtt_client.on_connect = MQTT_Helper.__on_mqtt_connect
      self.__mqtt_client.on_disconnect = MQTT_Helper.__on_mqtt_disconnect
      self.__mqtt_client.on_publish = MQTT_Helper.__on_mqtt_publish
      self.__mqtt_client.on_subscribe = MQTT_Helper.__on_mqtt_subscribe
      if settings.user or settings.password:
        self.__mqtt_client.username_pw_set(settings.user, settings.password)
    except Exception as e:
      logger.error(f"MQTT configuration is invalid: {e}")
      raise

  def __on_mqtt_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
      client.connected_flag = True
      client.bad_connection_flag = False
      logger.info("MQTT client connected.")      
    else:
      client.connected_flag = False
      client.bad_connection_flag = True
      logger.error(f"MQTT client connection error: {reason_code}")

  def __on_mqtt_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    logger.error(f"MQTT connection dropped: {reason_code}")
    client.connected_flag = False
    client.disconnect_flag = True

  def __on_mqtt_publish(client, userdata, mid, reason_code, properties):
    logger.info(f"Sent MQTT msg #{mid}")

  def __on_mqtt_subscribe(client, userdata, mid, reason_codes, properties):
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
  __worker = None
  def __register_bridge(bridge):
    if MQTT_InfluxDB_Bridge.__worker:
      raise Exception("Only one bridge instance is allowed.")
    MQTT_InfluxDB_Bridge.__worker = bridge

  def __on_mqtt_message(client, userdata, message):
    logger.debug(f"[get] Topic:{message.topic}, Data:{message.payload}")
    MQTT_InfluxDB_Bridge.__worker.__process_mqtt_message(message.topic, str(message.payload.decode('utf-8')))

  ############ Instance Level ##################
  def __init_mqtt(self, config, section):
    try:
      sectionConfig = config[section]
      settings = MQTTSettings()
      settings.server = sectionConfig["MQTTServer"].strip('\" ')
      settings.port = config.getint(section, "MQTTPort", fallback=1883)
      settings.user = sectionConfig["MQTTUser"].strip('\" ')
      settings.password = sectionConfig["MQTTPassword"].strip('\" ')
      settings.client_id = sectionConfig["MQTTClientId"].strip('\" ')
      self.__mqtt_helper = MQTT_Helper(settings)
    except Exception as e:
      logger.error(f"MQTT initialization failed: {e}")
      raise

  def __init_influxdb(self, config, section):
    try:
      sectionConfig = config[section]
      settings = InfluxDBConfig()
      settings.endpoint = sectionConfig["InfluxDBAPIEndPoint"].strip('\" ')
      settings.token = sectionConfig["InfluxDBAPIToken"].strip('\" ')
      settings.tenant = sectionConfig["InfluxDBTenant"].strip('\" ')
      settings.bucket = sectionConfig["InfluxDBBucket"].strip('\" ')
      self.__influxdb_helper = InfluxDBHelper(settings)
    except Exception as e:
      logger.error(f"InfluxDB initialization failed: {e}")
      raise

  def __init__(self, configfile):
    try:
      if not os.path.isfile(configfile):
        raise Exception(f"Config file [{configfile}] does not exist.")
      config = configparser.ConfigParser()
      config.read(configfile)
      self.__monitored_topics = config["Global"]["MonitoredTopics"]
      self.__init_mqtt(config, "MQTT")
      self.__init_influxdb(config, "InfluxDB")
      MQTT_InfluxDB_Bridge.__register_bridge(self)
    except Exception as e:
      logger.error(f"Config file {configfile} is invalid: {e}")
      raise

  def __process_mqtt_message(self, topic, message):
    try:
      # perform message format checking:
      # 1. only support two level topic: host/metric
      # 2. payload must be number
      parts = topic.split("/")
      if len(parts) != 2:
        raise Exception(f"Invalid topic path (host/metric expected).")
      host = parts[0]
      field = parts[1]
      value = int(message)
      logger.info(f"Send {host}:{field}={value}")
      self.__influxdb_helper.report_data(INFLUXDB_CATEGORY, host, field, value)
    except Exception as e:
      logger.error(f"Failed to process MQTT message (topic={topic}, msg={message}): {e}")

  def run(self):
    try:
      self.__mqtt_helper.subscribe(self.__monitored_topics, MQTT_InfluxDB_Bridge.__on_mqtt_message)
    except Exception as e:
      logger.error(f"MQTT2InfluxDB main function failed: {e}")

########################################
# CLI interface
########################################
def start_bridge(args):  
  bridge = MQTT_InfluxDB_Bridge(args.config)
  bridge.run()

#################################
# Program starts
#################################
if (__name__ == '__main__') and ('UNIT_TEST' not in os.environ):
  CLI_config = { 'func':start_bridge, 'arguments': [
    {'name':'config', 'help':'Config file for MQTT-to-InfluxDB bridge.'} 
    ]}
  CLIParser.run(CLI_config)
