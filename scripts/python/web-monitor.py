#!/usr/bin/env python3

import os
import json
import time

import requests
from urllib.parse import urlparse

import logging
logger = logging.getLogger()

class SendGrid:
  def __api_call(data):
    api_key = os.environ['SENDGRID_API_KEY'].strip('\"')
    api_endpoint = 'https://api.sendgrid.com/v3/mail/send'
    api_headers = { 'Authorization': f"Bearer {api_key}", 'Content-Type': 'application/json' }
    r = requests.post(api_endpoint, headers=api_headers, data=data)
    if r.status_code >= 400:
      raise Exception(f"SendGrid API failed ({r.status_code})")

  def send_email(sender, to, subject, body):
    sender = { 'email': sender }
    recipient = [{ 'email': to }]
    body = [{ 'type': 'text/html', 'value': body }]

    message = {}
    message['personalizations'] = [{ 'to': recipient }]
    message['from'] = sender
    message['subject'] = subject
    message['content'] = body

    SendGrid.__api_call(json.dumps(message))

# to start simple, this utility just do one-pass checking (no internal scheduler)
class WebMonitor:
  # class methods
  def is_valid_url(url):
    url = url.lower()
    if url.startswith('https://'):
      return True
    elif url.startswith('http://'):
      return True
    else:
      return False

  def is_online(url):
    error = None
    try:
      r = requests.get(url)
      if r.status_code < 400:
        return True, None

      error = f"HTTP error code: {r.status_code}"
    except Exception as e:
      error = f"Network error: {e}"

    return False, error

  # instance variables and methods
  def __init__(self):
    self.__sender = os.environ['MONITOR_SENDER']
    self.__recipient = os.environ['MONITOR_RECIPIENT']
    self.__hosts = []
    hosts_file = os.environ['MONITOR_HOSTS']
    with open(hosts_file, 'r') as f:
      lines = f.readlines()
      for line in lines:
        line = line.strip(' \r\'\"\n')
        if not line:
          continue
        if WebMonitor.is_valid_url(line):
          self.__hosts.append(line)
        else:
          logger.warning(f"Invalid URL in hosts list: {line}")

  def __send_email(self, url, error):
    parsed_uri = urlparse(url)
    host = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
    subject = f"[Web-Monitor]: {host} is down!"
    body = f"<b>Error details</b>: {error} <p> <b>URL</b>: {url}"
    SendGrid.send_email(self.__sender, self.__recipient, subject, body)

  def start(self):
    failed_hosts = []

    for url in self.__hosts:
      status, error = WebMonitor.is_online(url)
      if status:
        logger.debug(f"[{url}] is online.")
      else:
        # if fails, then retry after 5 min to decide
        logger.warning(f"[{url}] may be down, will confirm later: {error}")
        failed_hosts.append(url)

    if failed_hosts:
      time.sleep(300)
      for url in failed_hosts:
        status, error = WebMonitor.is_online(url)
        if status:
          logger.info(f"Host: {url} is up. (no email sent)")
        else:
          logger.error(f"[{url}] is down ({error}). Sending email...")
          self.__send_email(url, error)

AppName = "web-monitor"
def init_logger():
  app_logfile = f"/tmp/{AppName}.log"
  logFormatter = logging.Formatter("%(asctime)s: %(levelname)s - %(message)s")
  fileHandler = logging.FileHandler(app_logfile)
  fileHandler.setFormatter(logFormatter)
  logger.addHandler(fileHandler)
  consoleHandler = logging.StreamHandler()
  consoleHandler.setFormatter(logFormatter)
  logger.addHandler(consoleHandler)
  if 'DEBUG' in os.environ:
    logger.setLevel(logging.DEBUG)
  else:
    logger.setLevel(logging.INFO)

if __name__ == '__main__':
  init_logger()
  worker = WebMonitor()
  worker.start()
