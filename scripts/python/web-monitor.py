#!/usr/bin/env python3

import os, sys
import json
import time

import requests
from urllib.parse import urlparse

import argparse
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

class SendGrid:
  def __init__(self, api_key):
    self.__api_key = api_key.strip('\"')

  def __api_call(self, data):
    api_endpoint = 'https://api.sendgrid.com/v3/mail/send'
    api_headers = { 'Authorization': f"Bearer {self.__api_key}", 'Content-Type': 'application/json' }
    r = requests.post(api_endpoint, headers=api_headers, data=data)
    if r.status_code >= 400:
      raise Exception(f"SendGrid API failed ({r.status_code})")

  def send_email(self, sender, to, subject, body):
    sender = { 'email': sender }
    recipient = [{ 'email': to }]
    body = [{ 'type': 'text/html', 'value': body }]

    message = {}
    message['personalizations'] = [{ 'to': recipient }]
    message['from'] = sender
    message['subject'] = subject
    message['content'] = body

    self.__api_call(json.dumps(message))

class APIThrottlingException(Exception):
   """Raised when the API throttling happens"""
   pass

class SSLLabs:
  def __analyze_api_call(params):
    analyze_endpoint = 'https://api.ssllabs.com/api/v3/analyze'
    # force 2 seconds sleep to avoid hitting 529 (newAssessmentCoolOff)
    time.sleep(2)
    r = requests.get(analyze_endpoint, params=params)
    if r.status_code == 429 or r.status_code == 529:
      raise APIThrottlingException(f"SSLLabs API throttled: error={r.status_code}")
    elif r.status_code > 400:
      raise Exception(f"SSLLabs API failed: error={r.status_code}")
    return r.json()
  
  def track_server_load():
    try:
      info_endpoint = 'https://api.ssllabs.com/api/v3/info'
      # force 2 seconds sleep to avoid hitting 529 (newAssessmentCoolOff)
      time.sleep(2)
      r = requests.get(info_endpoint)
      if r.status_code > 400:
        logger.error(f"SSLLabs API failed: error={r.status_code}")
        return

      # log the current load
      result = r.json()
      logger.info(f"SSLLabs server info: load={result['currentAssessments']}/{result['maxAssessments']}, yield={result['newAssessmentCoolOff']/1000}s")
    except Exception as e:
      logger.error(f"Failed to get server info: {e}")

  def analyze_server(url):
    url = url.lower()
    if not url.startswith('https://'):
      raise Exception(f"Invalid URL to scan: {url}")

    payload = { 'host': url, 'fromCache': 'on', 'maxAge': 2 }
    result = SSLLabs.__analyze_api_call(payload)
    for i in range(0, 6):
      if result['status'] == 'READY':
        return result
      elif result['status'] == 'ERROR':
        raise Exception(f"SSLLabs API error: {result['statusMessage']}")

      # wait until we have a conclusion or timeout
      time.sleep(60)
      result = SSLLabs.__analyze_api_call(payload)
    raise Exception(f"Analyzing SSL timed out: {url}")

  def get_site_rating(url):
    ratings = []
    try:
      # track SSLLabs server load
      if 'DEBUG' in os.environ:
        SSLLabs.track_server_load()

      # start new assessment
      result = SSLLabs.analyze_server(url)
      endpoints = result['endpoints']
      for endpoint in endpoints:
        rating = { 'url': url, 'ip': endpoint['ipAddress'], 'grade': endpoint['grade'] }
        ratings.append(rating)
      return ratings
    except Exception as e:
      logger.error(f"{e}")
      if isinstance(e, APIThrottlingException):
        logger.info("Sleeping for a while to avoid further throttling.")
        time.sleep(900)
        return [{ 'url': url, 'ip': f"{e}", 'grade': 'Throttled' }]    
      else:
        return [{ 'url': url, 'ip': f"{e}", 'grade': 'Error' }]    

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

  def is_https(url):
    url = url.lower()
    if url.startswith('https://'):
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
  def __init__(self, sites_file):
    self.__load_email_config()
    self.__hosts = []
    try:
      with open(sites_file, 'r') as f:
        lines = f.readlines()
        for line in lines:
          line = line.strip(' \r\'\"\n')
          if not line:
            continue
          if WebMonitor.is_valid_url(line):
            if line not in self.__hosts:
              self.__hosts.append(line)
          else:
            logger.warning(f"Invalid URL in hosts list: {line}")
    except Exception as e:
      logger.critical(f"Cannot load site list file: {e}")
      sys.exit(1)

  def __load_email_config(self):
    self.__email_configured = False
    try:
      self.__email_api_key = os.environ['SENDGRID_API_KEY'].strip('\"')
      self.__email_sender = os.environ['MONITOR_SENDER']
      self.__email_recipient = os.environ['MONITOR_RECIPIENT']
      self.__email_configured = True
    except Exception as e:
      logger.warning(f"Email configuration incomplete: {e}")

  def __send_site_down_email(self, url, error):
    if not self.__email_configured:
      return

    parsed_uri = urlparse(url)
    host = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
    subject = f"[Web-Monitor]: {host} is down!"
    body = f"<b>Error details</b>: {error} <p> <b>URL</b>: {url}"
    sendgrid = SendGrid(self.__email_api_key)
    sendgrid.send_email(self.__email_sender, self.__email_recipient, subject, body)

  def __send_ssl_report(self, report):
    if not self.__email_configured or not report:
      return

    body_lines = []
    for item in report:
      grade = item['grade'].upper()
      if grade[0] == 'A':
        rating = f"<b style=\"color:green;\">{grade}</b>"
      else:
        rating = f"<b style=\"color:red;\">{grade}</b>"
      parsed_uri = urlparse(item['url'])
      host = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
      body_lines.append(f"{rating}: {host} ({item['ip']})<br>")

    today = time.strftime('%Y-%m-%d', time.localtime())
    subject = f"[{today}] SSL Rating Report"
    body = '\n'.join(body_lines)
    sendgrid = SendGrid(self.__email_api_key)
    sendgrid.send_email(self.__email_sender, self.__email_recipient, subject, body)

  def check_alive(self):
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
          self.__send_site_down_email(url, error)

  def check_ssl(self):
    full_report = []
    for url in self.__hosts:
      if not WebMonitor.is_https(url):
        continue

      logger.info(f"Checking SSL rating for {url}...")
      results = SSLLabs.get_site_rating(url)
      # retry once if failed
      if results[0]['grade'].lower() == 'throttled':
        logger.info(f"Retrying {url} after yielding ...")
        results = SSLLabs.get_site_rating(url)
      for result in results:
        logger.info(f"SSL rating: {result['grade']} ({result['ip']})")
        full_report.append(result)
    self.__send_ssl_report(full_report)

########################################
# CLI interface
########################################

def alive(args):
  logger.debug(f"CMD - Check if sites in [{args.file}] are alive")
  worker = WebMonitor(args.file)
  worker.check_alive()

def ssl(args):
  logger.debug(f"CMD - Check SSL rating of sites in [{args.file}]")
  worker = WebMonitor(args.file)
  worker.check_ssl()

#################################
# Program starts
#################################

if __name__ == '__main__':
  CLI_config = { 'commands': [
    { 'name': 'check-alive', 'help': 'Check if the sites in the file are alive', 'func': alive, 
      'params': [{ 'name': 'file', 'help': 'File contains list of sites'}] },
    { 'name': 'check-ssl', 'help': 'Check SSL rating of the sites in the file', 'func': ssl,
      'params': [{ 'name': 'file', 'help': 'File contains list of sites'}] }
    ]}
  parser = CLIParser.get_parser(CLI_config)
  CLIParser.run(parser)
