import logging
import colorlog
class Logger:
  def getLogger(app_name=None, log_to_file=True):
    logger = colorlog.getLogger(app_name)
    # console logger
    consoleHandler = logging.StreamHandler()
    console_log_format = "%(log_color)s%(asctime)s: %(message)s"
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
    if log_to_file:
      if not app_name:
        app_name = CLIParser.get_app_name()
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

  def disable_http_tracing():
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

import argparse
import os, sys
class CLIParser:
  def get_app_name():
    script = sys.argv[0]
    file_name = os.path.basename(script)
    return os.path.splitext(file_name)[0]

  def __get_cmd_parser(parser, commands):
    subparsers = parser.add_subparsers(title='commands')
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

  def __get_arg_parser(parser, config):
    arguments = config['arguments']
    for arg in arguments:
      parser.add_argument(arg['name'], help=arg['help'], action=arg.get('action'))
    parser.set_defaults(func=config['func'])
    return parser

  def get_parser(config):
    app_name = CLIParser.get_app_name()
    parser = argparse.ArgumentParser(app_name)
    if 'commands' in config:
      return CLIParser.__get_cmd_parser(parser, config['commands'])
    elif 'arguments' in config:
      return CLIParser.__get_arg_parser(parser, config)

  def run(parser):
    if len(sys.argv) == 1:
      # no arguments provided
      parser.print_help()
      sys.exit(0)

    args = parser.parse_args()
    args.func(args)