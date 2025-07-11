#!/usr/bin/env python3

import glob, os, time
import psutil
from influxdb import InfluxDBHelper
from common import Logger, CLIParser
logger = Logger.getLogger()

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
    try:
      # use psutil to get CPU temperature
      temps = psutil.sensors_temperatures()
      if 'coretemp' in temps:  # Intel CPUs
        core_temps = [t.current for t in temps['coretemp']]
        return max(core_temps)
      elif 'k10temp' in temps:  # AMD CPUs
        return temps['k10temp'][0].current

      # Temperature sensors not supported by psutil, try system files (Linux only)
      temps = []
      for thermal_zone in glob.glob('/sys/class/thermal/thermal_zone*/temp'):
        with open(thermal_zone, 'r') as f:
          temp = int(f.read().strip()) / 1000  # Convert millidegrees to °C
          temps.append(temp)
      return max(temps) if temps else None
    except Exception as e:
      logger.error(f"Failed to read CPU temperature: {e}")
      return None

class FanControl:
  __fan_gpio = None
  __fan_on_temperature = 50
  __fan_off_temperature = 40

  def init(gpio, temp_on, temp_off):
    from gpiozero import OutputDevice
    
    # Validate the on and off thresholds
    if temp_off >= temp_on:
      raise Exception('OFF_THRESHOLD {temp_off} must be less than ON_THRESHOLD {temp_on}')

    try:
      FanControl.__fan_gpio = OutputDevice(gpio)
      FanControl.__fan_on_temperature = temp_on
      FanControl.__fan_off_temperature = temp_off
      status = FanControl.__fan_gpio.value
      logger.debug(f"Fan control for [{temp_off}-{temp_on}] initialized. (GPIO={gpio}, Status={status})")
    except Exception as e:
      logger.error(f"Failed to initialize fan control GPIO pin: {e}")

  def is_available():
    return FanControl.__fan_gpio is not None

  def is_on():
    if not FanControl.is_available():
      return False
    # NOTE: `fan.value` returns 1 for "on" and 0 for "off"
    return FanControl.__fan_gpio.value == 1

  def turn_on():
    if FanControl.is_available():
      FanControl.__fan_gpio.on()

  def turn_off():
    if FanControl.is_available():
      FanControl.__fan_gpio.off()

  def auto_control(temp):
    if not temp or not FanControl.is_available():
      return

    # Start the fan if the temperature has reached the limit and the fan
    # isn't already running.
    if temp > FanControl.__fan_on_temperature and not FanControl.is_on():
      logger.info(f"Turn on fan. (temperature={temp})")
      FanControl.turn_on()

    # Stop the fan if the fan is running and the temperature has dropped
    # to 10 degrees below the limit.
    elif FanControl.is_on() and temp < FanControl.__fan_off_temperature:
      logger.info(f"Turn off fan. (temperature={temp})")
      FanControl.turn_off()

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
    
    FanControl.auto_control(temp)
  except Exception as e:
    logger.error(f"Exception: {e}")

if __name__ == '__main__':
  if 'FAN_CONTROL_PIN' in os.environ:
    # need to control fan
    gpio_pin = int(os.environ['FAN_CONTROL_PIN'].strip('\" '))
    fan_on_temp = 50
    fan_off_temp = 40
    if 'FAN_ON_TEMP' in os.environ:
      fan_on_temp = int(os.environ['FAN_ON_TEMP'].strip('\" '))
    if 'FAN_OFF_TEMP' in os.environ:
      fan_off_temp = int(os.environ['FAN_OFF_TEMP'].strip('\" '))
    FanControl.init(gpio_pin, fan_on_temp, fan_off_temp)

  settings = InfluxDBHelper.load_influxDB_config()
  writer = InfluxDBHelper(settings)
  while True:
    time.sleep(SLEEP_INTERVAL)
    monitor_metrics(writer)
