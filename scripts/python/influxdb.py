#!/usr/bin/env python3

import datetime
import os
# for struct-like class
from dataclasses import dataclass
# InfluxDB
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS
# logging
from common import Logger, CLIParser
logger = Logger.getLogger()

@dataclass
class InfluxDBConfig:
  api_endpoint: str = None
  api_key: str = None
  tenant: str = None
  bucket: str = None

class InfluxDBHelper:
  def load_influxDB_config():
    try:
      settings = InfluxDBConfig()
      settings.endpoint = os.environ['INFLUXDB_API_ENDPOINT'].strip('\" ')
      settings.token = os.environ['INFLUXDB_API_TOKEN'].strip('\" ')
      settings.tenant = os.environ['INFLUXDB_TENANT'].strip('\" ')
      settings.bucket = os.environ['INFLUXDB_BUCKET'].strip('\" ')
      return settings
    except Exception as e:
      logger.error(f"Failed to get InfluxDB configuration from ENV: {e}")
      raise

  def __init__(self, influxDB_config):
    try:
      logger.debug(f"Initialize InfluxDB...")
      self._settings = influxDB_config
      self._client = InfluxDBClient(url=influxDB_config.endpoint, token=influxDB_config.token)
      self._write_client = self._client.write_api(write_options=SYNCHRONOUS)
    except Exception as e:
      logger.error(f"Failed to initialize InfluxDB: {e}")

  def report_data(self, category, host, data, value):
    try:
      point = Point(category) \
        .tag("host", host) \
        .field(data, value) \
        .time(datetime.datetime.utcnow(), WritePrecision.NS)

      self._write_client.write(self._settings.bucket, self._settings.tenant, point)
    except Exception as e:
      logger.error(f"Failed to report data to InfluxDB: {e}")

  def report_data_list(self, category, host, data):
    try:
      point = Point(category)
      point.tag("host", host)
      for field_key, field_value in data:
        point.field(field_key, field_value)
      point.time(datetime.datetime.utcnow(), WritePrecision.NS)

      self._write_client.write(self._settings.bucket, self._settings.tenant, point)
    except Exception as e:
      logger.error(f"Failed to report data to InfluxDB: {e}")
