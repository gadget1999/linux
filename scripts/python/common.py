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

import argparse
import os, sys
class CLIParser:
  def get_app_name():
    script = sys.argv[0]
    file_name = os.path.basename(script)
    return os.path.splitext(file_name)[0]

  def get_parser(config):
    app_name = CLIParser.get_app_name()
    parser = argparse.ArgumentParser(app_name)
    subparsers = parser.add_subparsers(title='commands')
    # parse commands
    commands = config['commands']
    for command in commands:
      cmd_name = command['name']
      cmd_help = command['help']
      cmd_func = command['func']
      cmd_parser = subparsers.add_parser(cmd_name, help=cmd_help)
      cmd_parser.set_defaults(func=cmd_func)
      # optionally parse params for the command
      if 'params' in command:
        cmd_params = command['params']
        for cmd_param in cmd_params:
          param_name = cmd_param['name']
          param_help = cmd_param['help']
          nargs = None
          if 'multi-value' in cmd_param:
            nargs = "+"
          cmd_parser.add_argument(param_name, nargs=nargs, help=param_help)

    return parser

  def run(parser):
    if len(sys.argv) == 1:
      # no arguments provided
      parser.print_help()
      sys.exit(0)

    args = parser.parse_args()
    args.func(args)