import logging
import colorlog
class Logger:
  __logger = None

  def getLogger(app_name=None, log_to_file=True):
    # reuse existing logger
    if Logger.__logger:
      return Logger.__logger
    # create new logger
    Logger.__logger = colorlog.getLogger(app_name)
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
    Logger.__logger.addHandler(consoleHandler)
    if log_to_file:
      if "APP_NAME" in os.environ:
        app_name = os.environ["APP_NAME"]
      if not app_name:
        app_name = CLIParser.get_app_name()
      app_logfile = f"/tmp/{app_name}.log"
      try:
        fileHandler = logging.FileHandler(app_logfile, encoding = "UTF-8", delay = True)
        file_log_format = "%(asctime)s: %(levelname)s - %(message)s"
        fileHandler.setFormatter(logging.Formatter(file_log_format))
        fileHandler.setLevel(logging.INFO)
        Logger.__logger.addHandler(fileHandler)
      except Exception as e:
        Logger.__logger.error(f"Cannot open log file [{app_logfile}]: {e}")
    # set log level
    Logger.__logger.setLevel(logging.DEBUG)
    return Logger.__logger

  def disable_http_tracing():
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

import signal
class ExitSignal:
  exit_flag = False

  def __exit_handler(signum, frame):
    exit_flag = True
    logger = Logger.getLogger()
    logger.critical(f"Exit signal [{signum}] is captured, exiting...")
    sys.exit(2)

  def register():
    signal.signal(signal.SIGINT, ExitSignal.__exit_handler)

import argparse
import os, sys
def non_empty_string(value):
  if not value.strip():
    raise argparse.ArgumentTypeError("Value cannot be empty!")
  return value

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
          if param_name.startswith('-'):
            # parameter is a flag
            action = cmd_param['action'] if 'action' in cmd_param else None
            cmd_parser.add_argument(param_name, action=action, help=param_help)
          else:
            # named parameter
            nargs = "+" if 'multi-value' in cmd_param else None
            cmd_parser.add_argument(param_name, nargs=nargs, help=param_help)
    return parser

  def __get_arg_parser(parser, config):
    arguments = config['arguments']
    for arg in arguments:
      if 'required' in arg and arg['required']:
        parser.add_argument(arg['name'], help=arg['help'], action=arg.get('action'),
                            required=True, type=non_empty_string)
      else:
        parser.add_argument(arg['name'], help=arg['help'], action=arg.get('action'))
    parser.set_defaults(func=config['func'])
    return parser

  def __get_parser(config):
    app_name = CLIParser.get_app_name()
    parser = argparse.ArgumentParser(app_name)
    if 'commands' in config:
      return CLIParser.__get_cmd_parser(parser, config['commands'])
    elif 'arguments' in config:
      return CLIParser.__get_arg_parser(parser, config)

  def run(CLI_config):
    # for capturing Ctrl-C
    ExitSignal.register()
    try:
      parser = CLIParser.__get_parser(CLI_config)
      if len(sys.argv) == 1:
        # no arguments provided
        parser.print_help()
        sys.exit(0)
      args = parser.parse_args()
      args.func(args)
    except Exception as e:
      logger = Logger.getLogger()
      logger.exception(f"Exception happened: {e}")
      sys.exit(1)
