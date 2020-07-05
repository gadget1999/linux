#!/usr/bin/env python3

import os, sys
import http.server, ssl

# for logging and CLI arguments parsing
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

class WebFileServer:
  def start_instance(root_dir, port=80, cert_file=None, key_file=None):
    Handler = http.server.SimpleHTTPRequestHandler
    os.chdir(root_dir)
    httpd = http.server.HTTPServer(('', port), Handler)
    if cert_file and key_file:
      logger.info(f"Starting HTTPS server: port={port}, path={root_dir}")
      httpd.socket = ssl.wrap_socket (httpd.socket, server_side=True,
        keyfile=key_file, certfile=cert_file)
    else:
      logger.info(f"Starting HTTP server: port={port}, path={root_dir}")
    httpd.serve_forever()

########################################
# CLI interface
########################################

def start_web_server(args):
  WebFileServer.start_instance(args.root_dir, int(args.port), args.cert_file, args.key_file)

#################################
# Program starts
#################################
def handler(signal_received, frame):
  logger.critical("Ctrl-C signal is captured, exiting...")
  sys.exit(2)

if (__name__ == '__main__') and ('UNIT_TEST' not in os.environ):
  # for capturing Ctrl-C
  from signal import signal, SIGINT

  signal(SIGINT, handler)
  CLI_config = { 'func':start_web_server, 'arguments': [
    {'name':'root_dir', 'help':'Root folder for directory'}, 
    {'name':'port', 'help':'Port for the web server'}, 
    {'name':'--cert_file', 'help':'SSL certificate file'},
    {'name':'--key_file', 'help':'SSL key file'}
    ]}
  try:
   parser = CLIParser.get_parser(CLI_config)
   CLIParser.run(parser)
  except Exception as e:
   logger.error(f"Exception happened: {e}")
   sys.exit(1)
