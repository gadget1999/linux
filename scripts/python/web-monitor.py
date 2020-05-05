#!/usr/bin/env python3

import os, sys
import json
import time, datetime
# for web APIs
import requests
from urllib.parse import urlparse
# for SSL
import socket
import ssl
# for email and HTML body
from jinja2 import Template
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, MimeType
# for logging and CLI arguments parsing
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

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

  def get_ssl_expiration_date(url):
    try:
      parsed_uri = urlparse(url)
      host = parsed_uri.hostname
      port = parsed_uri.port
      if not port:
        port = 443
      context = ssl.create_default_context()
      with socket.create_connection((host, port)) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
          cert_info = ssock.getpeercert()
          ssl_date_fmt = r'%b %d %H:%M:%S %Y %Z'
          return datetime.datetime.strptime(cert_info['notAfter'], ssl_date_fmt)
    except Exception as e:
      logger.error(f"Failed to get expiration date for {url}: {e}")
      return datetime.datetime.now()

  def get_ssl_expiration_in_days(url):
    now = datetime.datetime.now()
    dt = SSLLabs.get_ssl_expiration_date(url)
    return (dt - now).days

# to start simple, this utility just do one-pass checking (no internal scheduler)
class WebMonitor:
  __html_SSL_report_template = """
<html>
 <head><title>SSL Report</title></head>
 <body>
  <p>
  SSL rating report from API provided by: https://www.ssllabs.com/ssltest/index.html
  </p>
  <b>Rating, Expires in days, URL, IP (or error)</b><br>
  {%- for site in sites %}
   {% if site.grade.startswith('A') %}
    <b style=\"color:green;\">{{ site.grade }}</b>, 
   {% else %}
    <b style=\"color:red;\">{{ site.grade }}</b>, 
   {% endif %}
   {% if site.expires|int < 60 %}
    <b style=\"color:red;\">{{ site.expires }}</b>, 
   {% else %}
    {{ site.expires }}, 
   {% endif %}
   {{ site.url }}, {{ site.ip }}
   {% if not loop.last %}<br>{% endif %}
  {%- endfor %}
 </body>
</html>
"""

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
      self.__email_api_key = os.environ['SENDGRID_API_KEY'].strip('\" ')
      self.__email_sender = os.environ['MONITOR_SENDER'].strip('\" ')
      self.__email_recipients = os.environ['MONITOR_RECIPIENTS'].strip('\" ').split(';')
      self.__email_configured = True
    except Exception as e:
      logger.warning(f"Email configuration incomplete: {e}")

  def __send_site_down_email(self, url, error):
    if not self.__email_configured:
      return

    try:
      # construct email
      email = Mail()
      email.from_email = self.__email_sender
      for recipient in self.__email_recipients:
        email.add_to(recipient)
      parsed_uri = urlparse(url)
      host = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
      email.subject = f"[Web-Monitor]: {host} is down!"
      email.add_content(f"<b>Error details</b>: {error} <p> <b>URL</b>: {url}", MimeType.html)
      # send email
      sendgrid = SendGridAPIClient(self.__email_api_key)
      r = sendgrid.send(email)
      if r.status_code > 400:
        logger.error(f"SendGrid API failed: error={r.status_code}")
    except Exception as e:
      logger.error(f"Failed to send Site Down Report: {e}")

  def __send_ssl_report(self, report):
    if not self.__email_configured or not report:
      return

    try:
      # construct email
      email = Mail()
      email.from_email = self.__email_sender
      for recipient in self.__email_recipients:
        email.add_to(recipient)
      today = time.strftime('%Y-%m-%d', time.localtime())
      email.subject = f"[{today}] SSL Rating Report"
      engine = Template(WebMonitor.__html_SSL_report_template)
      email.add_content(engine.render(sites=report), MimeType.html)
      # send email
      sendgrid = SendGridAPIClient(self.__email_api_key)
      r = sendgrid.send(email)
      if r.status_code > 400:
        logger.error(f"SendGrid API failed: error={r.status_code}")
    except Exception as e:
      logger.error(f"Failed to send Site SSL Report: {e}")

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
      expires = SSLLabs.get_ssl_expiration_in_days(url)
      for result in results:
        logger.info(f"SSL rating: {result['grade']} ({result['ip']}): expires in {expires} days.")
        result['expires'] = expires
        full_report.append(result)
    self.__send_ssl_report(full_report)

########################################
# CLI interface
########################################

def check_alive(args):
  logger.debug(f"CMD - Check if sites in [{args.file}] are alive")
  worker = WebMonitor(args.file)
  worker.check_alive()

def check_ssl(args):
  logger.debug(f"CMD - Check SSL rating of sites in [{args.file}]")
  worker = WebMonitor(args.file)
  worker.check_ssl()

#################################
# Program starts
#################################

if __name__ == '__main__':
  CLI_config = { 'commands': [
    { 'name': 'check-alive', 'help': 'Check if the sites in the file are alive', 'func': check_alive, 
      'params': [{ 'name': 'file', 'help': 'File contains list of sites'}] },
    { 'name': 'check-ssl', 'help': 'Check SSL rating of the sites in the file', 'func': check_ssl,
      'params': [{ 'name': 'file', 'help': 'File contains list of sites'}] }
    ]}
  parser = CLIParser.get_parser(CLI_config)
  CLIParser.run(parser)
