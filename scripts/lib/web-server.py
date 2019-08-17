#!/usr/bin/env python3
#
#  echo -n "<username>:<password>" | base64
#
import os
import ssl
import logging
import argparse
import http.server
from base64 import b64decode

# Logging Setup
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

class BasicAuthHandler(http.server.SimpleHTTPRequestHandler):
    key = ''

    def do_HEAD(self):
        '''Send Headers'''
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_AUTHHEAD(self):
        '''Send Basic Auth Headers'''
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic')
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    def do_GET(self):
        '''Handle GET Request'''
        try:
            if self.headers.get('Authorization') is None:
                # Send Auth Headers
                self.do_AUTHHEAD()
                logger.debug('Auth Header Not Found')
                self.wfile.write(bytes('Unauthorized', 'utf8'))
            elif self.headers.get('Authorization') == 'Basic ' + self.key:
                # Successful Auth
                http.server.SimpleHTTPRequestHandler.do_GET(self)
            else:
                # Bad Credentials Supplied
                self.do_AUTHHEAD()
                auth_header = self.headers.get('Authorization')
                # Log Bad Credentials
                if len(auth_header.split(' ')) > 1:
                    logger.debug(auth_header.split(' ')[1])
                    logger.debug(b64decode(auth_header.split(' ')[1]))
                logger.debug('Bad Creds')
                self.wfile.write(bytes('Unauthorized', 'utf8'))
        except Exception:
            logger.error("Error in GET Functionality", exc_info=True)

    def date_time_string(self, time_fmt='%s'):
        return ''

    def log_message(self, format, *args):
        '''Requests Logging'''
        logger.debug("%s - - [%s] %s" % (self.client_address[0],
            self.log_date_time_string(),
            format % args))


if __name__ == '__main__':

    # Initialize the arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", "-p", help="set the port of web server")
    parser.add_argument("--key", "-k", help="set the authentication key")
    parser.add_argument("--cert", "-c", help="set the TLS certificate path")
    parser.add_argument("--root", "-r", help="set the root folder")
    args = parser.parse_args()

    # Create Handler Instance
    handler = BasicAuthHandler
    handler.server_version = ' Python HTTPS Server v1.0 '
    handler.sys_version = ''
    handler.key = args.key

    # SimpleHTTPServer Setup
    port = int(args.port)
    httpd = http.server.HTTPServer(('0.0.0.0', port), handler)

    cert = args.cert
    httpd.socket = ssl.wrap_socket(httpd.socket, certfile=cert, server_side=True)
    try:
        root = args.root
        os.chdir(root)
        httpd.serve_forever()
    except Exception:
        logger.error("Fatal error in main loop", exc_info=True)
