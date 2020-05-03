import logging
import colorlog

class Logger:
  def getLogger(app_name=None):
    logger = colorlog.getLogger(app_name)
    # console logger
    consoleHandler = logging.StreamHandler()
    consoleHandler.setFormatter(colorlog.ColoredFormatter("%(log_color)s:%(asctime)s: %(message)s"))
    consoleHandler.setLevel(logging.DEBUG)
    logger.addHandler(consoleHandler)
    # file logger if app name is set
    if app_name:
      app_logfile = f"/tmp/{app_name}.log"
      try:
        fileHandler = logging.FileHandler(app_logfile)
        fileHandler.setFormatter(logging.Formatter("%(asctime)s: %(levelname)s - %(message)s"))
        fileHandler.setLevel(logging.INFO)
        logger.addHandler(fileHandler)
      except Exception as e: 
        logger.error(f"Cannot open log file [{app_logfile}]: {e}")
    # set log level
    logger.setLevel(logging.DEBUG)
    return logger
