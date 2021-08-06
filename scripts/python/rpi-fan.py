#!/usr/bin/env python3

import os, time
from gpiozero import OutputDevice
import psutil
from influxdb import InfluxDBHelper
from common import Logger, CLIParser
logger = Logger.getLogger()

TEMP_FAN_ON = 50  # (degrees Celsius) Fan kicks on at this temperature.
TEMP_FAN_OFF = 40  # (degress Celsius) Fan shuts off at this temperature.
SLEEP_INTERVAL = 30  # (seconds) How often we check the core temperature.

INFLUXDB_TOPIC = "Metrics"
INFLUXDB_HOST = os.uname()[1]

class SystemMetrics:
  __has_temperature_sensor = True

  def cpu_usage():
    return psutil.cpu_percent()

  def memory_usage():
    return psutil.virtual_memory().percent

  def disk_usage():
    return psutil.disk_usage('/').percent

  def cpu_temperature():
    if not SystemMetrics.__has_temperature_sensor:
      return None

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
      logger.error(f"Could not read CPU temperature: {e}. Treating as no sensor.")
      SystemMetrics.__has_temperature_sensor = False
      return None

class FanControl:
  __fan_gpio = None

  def init():
    try:
      if 'FAN_ON_TEMP' in os.environ:
        TEMP_FAN_ON = int(os.environ['FAN_ON_TEMP'].strip('\" '))
        logger.debug(f"Fan on temperature: {TEMP_FAN_ON}")
      if 'FAN_OFF_TEMP' in os.environ:
        TEMP_FAN_OFF = int(os.environ['FAN_OFF_TEMP'].strip('\" '))
        logger.debug(f"Fan off temperature: {TEMP_FAN_OFF}")
      if 'FAN_CONTROL_PIN' in os.environ:
        # need to control fan
        gpio_pin = int(os.environ['FAN_CONTROL_PIN'].strip('\" '))
        FanControl.__fan_gpio = OutputDevice(gpio_pin)
        logger.debug(f"Fan control initialized. (GPIO={gpio_pin}, Status={FanControl.__fan_gpio.value})")
    except Exception as e:
      logger.error(f"Failed to initialize fan control GPIO pin: {e}")

  def is_available():
    return FanControl.__fan_gpio is not None

  def is_on():
    if FanControl.__fan_gpio is None:
      return False
    # NOTE: `fan.value` returns 1 for "on" and 0 for "off"
    return FanControl.__fan_gpio.value == 1

  def turn_on():
    if FanControl.__fan_gpio is not None:
      FanControl.__fan_gpio.on()

  def turn_off():
    if FanControl.__fan_gpio is not None:
      FanControl.__fan_gpio.off()

def monitor_metrics(influxdb_writer):
  try:
    temp = SystemMetrics.cpu_temperature()
    #writer.report_data(INFLUXDB_TOPIC, INFLUXDB_HOST, INFLUXDB_PROP_TEMP, temp)
    data = []
    if temp: data.append(("CPU_Temp", temp))
    data.append(("CPU_Load", SystemMetrics.cpu_usage()))
    data.append(("RAM_Use", SystemMetrics.memory_usage()))
    data.append(("Disk_Use", SystemMetrics.disk_usage()))
    if 'DEBUG' in os.environ or FanControl.is_on():
      logger.debug(f"{data}")
    influxdb_writer.report_data_list(INFLUXDB_TOPIC, INFLUXDB_HOST, data)

    if not temp or not FanControl.is_available():
      return

    # Start the fan if the temperature has reached the limit and the fan
    # isn't already running.
    if temp > TEMP_FAN_ON and not FanControl.is_on():
      logger.info(f"Turn on fan. (temperature={temp})")
      FanControl.turn_on()

    # Stop the fan if the fan is running and the temperature has dropped
    # to 10 degrees below the limit.
    elif FanControl.is_on() and temp < TEMP_FAN_OFF:
      logger.info(f"Turn off fan. (temperature={temp})")
      FanControl.turn_off()

  except Exception as e:
    logger.error(f"Exception: {e}")

if __name__ == '__main__':
  # Validate the on and off thresholds
  if TEMP_FAN_OFF >= TEMP_FAN_ON:
    raise Exception('OFF_THRESHOLD must be less than ON_THRESHOLD')

  FanControl.init()
  settings = InfluxDBHelper.load_influxDB_config()
  writer = InfluxDBHelper(settings)
  while True:
    time.sleep(SLEEP_INTERVAL)
    monitor_metrics(writer)
