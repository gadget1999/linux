#!/usr/bin/env python3

import os, time
from gpiozero import OutputDevice
import psutil
from influxdb import InfluxDBHelper
from common import Logger, CLIParser
logger = Logger.getLogger()

ON_THRESHOLD = 50  # (degrees Celsius) Fan kicks on at this temperature.
OFF_THRESHOLD = 40  # (degress Celsius) Fan shuts off at this temperature.
SLEEP_INTERVAL = 10  # (seconds) How often we check the core temperature.
GPIO_PIN = 18  # Which GPIO pin you're using to control the fan.

INFLUXDB_TOPIC = "Metrics"
INFLUXDB_HOST = os.uname()[1]
INFLUXDB_PROP_CPU = "CPU_Load"
INFLUXDB_PROP_TEMP = "CPU_Temp"

def get_cpu():
  return psutil.cpu_percent()

def get_temp():
  """Get the core temperature.
  Read file from /sys to get CPU temp in temp in C *1000
  Returns:
    int: The core temperature in thousanths of degrees Celsius.
  """
  try:
    temp_str = None
    with open('/sys/class/thermal/thermal_zone0/temp') as f:
      temp_str = f.read()

    return int(temp_str) / 1000
  except Exception as e:
    logger.error(f"Could not read CPU temperature: {e}")

if __name__ == '__main__':
  # Validate the on and off thresholds
  if OFF_THRESHOLD >= ON_THRESHOLD:
    raise Exception('OFF_THRESHOLD must be less than ON_THRESHOLD')

  fan = OutputDevice(GPIO_PIN)
  settings = InfluxDBHelper.load_influxDB_config()
  writer = InfluxDBHelper(settings)  
  while True:
    cpu = get_cpu()
    temp = get_temp()
    writer.report_data(INFLUXDB_TOPIC, INFLUXDB_HOST, INFLUXDB_PROP_CPU, cpu)
    writer.report_data(INFLUXDB_TOPIC, INFLUXDB_HOST, INFLUXDB_PROP_TEMP, temp)

    # Start the fan if the temperature has reached the limit and the fan
    # isn't already running.
    # NOTE: `fan.value` returns 1 for "on" and 0 for "off"
    if temp > ON_THRESHOLD and fan.value == 0:
      logger.info(f"Turn on fan. (temperature={temp})")
      fan.on()

    # Stop the fan if the fan is running and the temperature has dropped
    # to 10 degrees below the limit.
    elif fan.value == 1 and temp < OFF_THRESHOLD:
      logger.info(f"Turn off fan. (temperature={temp})")
      fan.off()

    if 'DEBUG' in os.environ or fan.value == 1:
      logger.debug(f"Temp={temp}, PIN state={fan.value}")
    time.sleep(SLEEP_INTERVAL)
