import logging
import colorlog

class Logger:
  def getLogger(app_name=None):
    logger = colorlog.getLogger(app_name)
    # console logger
    consoleHandler = logging.StreamHandler()
    console_log_format = "%(log_color)s:%(asctime)s: %(message)s"
    console_log_colors = {
                'DEBUG':    'yellow',
                'INFO':     'green',
                'WARNING':  'purple',
                'ERROR':    'red',
                'CRITICAL': 'red,bg_white',
        }
    console_log_formatter = colorlog.ColoredFormatter(console_log_format, log_colors=console_log_colors)
    consoleHandler.setFormatter(console_log_formatter)
    consoleHandler.setLevel(logging.DEBUG)
    logger.addHandler(consoleHandler)
    # file logger if app name is set
    if app_name:
      app_logfile = f"/tmp/{app_name}.log"
      try:
        fileHandler = logging.FileHandler(app_logfile)
        file_log_format = "%(asctime)s: %(levelname)s - %(message)s"
        fileHandler.setFormatter(logging.Formatter(file_log_format))
        fileHandler.setLevel(logging.INFO)
        logger.addHandler(fileHandler)
      except Exception as e:
        logger.error(f"Cannot open log file [{app_logfile}]: {e}")
    # set log level
    logger.setLevel(logging.DEBUG)
    return logger
