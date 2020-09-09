#!/usr/bin/env python3

import os, sys
import json
import time, datetime
# for struct-like class
import copy
from dataclasses import dataclass
# for web APIs
import socket, ipaddress
import requests
from urllib.parse import urlparse
# for unittest
import unittest
# for logging and CLI arguments parsing
import configparser
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

def get_ip_addresses(host, port):
  try:
    addresses = []
    addrInfo = socket.getaddrinfo(host, port)
    for addr in addrInfo:
      addresses.append(addr[4][0])
    if addresses:
      return addresses, None
    else:
      return None, f"Failed to get IP addresses for {host}"
  except Exception as e:
    return None, f"Failed to get IP addresses for {host}: {e}"

def get_ip_location(ip):
  try:
    url = f"https://ipinfo.io/{ip}/json"
    time.sleep(2)   # avoid throttling
    r = requests.get(url)
    if r.status_code >= 400:
      logger.warning(f"Failed to get location of IP: {ip} (status={r.status_code})")
      return None, None, None
    data = r.json()
    city = data['city']
    region = data['region']
    country = data['country']
    return city, region, country
  except Exception as e:
    logger.warning(f"Failed to get location of IP: {ip} ({e})")
    return None, None, None

def get_url_location(url):
  try:
    parsed_uri = urlparse(url)
    ip = socket.gethostbyname(parsed_uri.hostname)
    return get_ip_location(ip)
  except Exception as e:
    logger.warning(f"Failed to get location of url: {url} ({e})")
    return None, None, None

def is_ipv6(ip):
  try:
    ipaddress.IPv6Address(ip)
    return True
  except:
    return False

def is_valid_dns(fqdn):
  try:
    socket.gethostbyname(fqdn)
    return True, None
  except Exception as e:
    return False, f"Failed to resolve {fqdn}: {e}"

@dataclass
class SSLRecord:
  url: str
  report: str = ''
  ip: str = ''
  grade: str = ''
  expires: str = ''
  error: str = ''

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
  
  def __track_server_load():
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

  def __analyze_server(url):
    parsed_uri = urlparse(url)
    if parsed_uri.scheme != 'https':
      raise Exception(f"Invalid URL to scan: {url}")

    payload = { 'host': url, 'fromCache': 'on', 'maxAge': 24 }
    result = SSLLabs.__analyze_api_call(payload)
    for i in range(0, 6):
      if result['status'].lower() == 'ready':
        return result
      elif result['status'].lower() == 'error':
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
        SSLLabs.__track_server_load()
      # start new assessment
      try:
        logger.info(f"Checking SSL rating for {url}...")
        result = SSLLabs.__analyze_server(url)
      except APIThrottlingException:
        # retry after a while if throttled
        logger.info("Sleeping for a while to avoid further throttling.")
        time.sleep(900)
        result = SSLLabs.__analyze_server(url)
      endpoints = result['endpoints']
      parsed_uri = urlparse(url)
      report_url = f"https://www.ssllabs.com/ssltest/analyze.html?d={parsed_uri.hostname}&hideResults=on"
      for endpoint in endpoints:
        rating = SSLRecord(url=url, report=report_url, ip=endpoint['ipAddress'])
        if is_ipv6(rating.ip):
          # skip non IPv4 address as Azure VM doesn't support it well yet
          continue
        if endpoint['statusMessage'].lower() != 'ready':
          rating.error = endpoint['statusMessage']
          rating.grade = 'Error'
        else:
          rating.grade = endpoint['grade']
        ratings.append(rating)
      return ratings
    except Exception as e:
      logger.error(f"{e}")
      return [SSLRecord(url=url, grade='Error', error=f"{e}")]

  def __get_ssl_expiration_date(host, ip=None, port=443):
    import ssl

    try:
      if not ip:
        ip = host
      if not port:
        port = 443
      logger.debug(f"Getting SSL certificate info: {ip}:{port}")
      context = ssl.create_default_context()
      with socket.create_connection((ip, port)) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
          cert_info = ssock.getpeercert()
          ssl_date_fmt = r'%b %d %H:%M:%S %Y %Z'
          expire_time = datetime.datetime.strptime(cert_info['notAfter'], ssl_date_fmt)
          logger.debug(f"Expiration time: {expire_time.strftime('%Y-%m-%d')}")          
          return expire_time, None
    except Exception as e:
      error = f"Failed to get expiration date for {host}: {e}"
      logger.error(error)
      return None, error

  def get_ssl_expires_in_days(url, ip=None, check_endpoints=False):
    parsed_uri = urlparse(url)
    host = parsed_uri.hostname
    port = parsed_uri.port
    if ip:
      # only scan specified endpoint
      addresses = [ip]
    elif check_endpoints:
      # check all endpoints
      addresses, error = get_ip_addresses(host, port)
      if error:
        logger.error(f"{error}")
        addresses = ['']
    else:
      # only check site, not endpoints
      addresses = ['']
    # get results for every endpoint
    results = []
    for ip in addresses:
      result = SSLRecord(url=url, ip=ip)
      expires, error = SSLLabs.__get_ssl_expiration_date(host, ip, port)
      if error:
        result.error = error
      else:
        result.expires = (expires - datetime.datetime.now()).days
      results.append(result)
    return results

class SSLLabsTestCase(unittest.TestCase):
  def test_get_ssl_ratings(self):
    rating = SSLLabs.get_site_rating("https://www.google.com")
    self.assertEqual(len(rating), 2, 'wrong number of records')
    rating = SSLLabs.get_site_rating("https://www.google1.com")
    self.assertEqual(len(rating), 1, 'wrong number of records')
  def test_get_ssl_expiration(self):
    report = SSLLabs.get_ssl_expires_in_days("https://www.indiaglitz.com", check_endpoints=True)
    self.assertEqual(len(report), 4, 'wrong number of records')
    report = SSLLabs.get_ssl_expires_in_days("https://www.indiaglitz.com")
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SSLLabs.get_ssl_expires_in_days("https://www.google1.com")
    self.assertEqual(len(report), 1, 'wrong number of records')

if 'UNIT_TEST' in os.environ:
  test = SSLLabsTestCase()
  #test.test_get_ssl_ratings()
  #test.test_get_ssl_expiration()

@dataclass
class SiteRecord:
  url: str
  alive: bool = False
  online: bool = False
  ip: str = ''
  error: str = ''
  ssl_expires: str = ''
  ssl_rating: str = ''
  ssl_report: str = ''

class SiteInfo:
  def is_valid_url(url):
    url = url.lower()
    if url.startswith('https://'):
      return True
    elif url.startswith('http://'):
      return True
    else:
      return False

  # return alive (if reachable), online (if functional) and error if any
  def is_online(url):
    try:
      logger.debug(f"Checking [{url}] status...")
      headers = {"Accept-Language": "en-US,en;q=0.5"}
      time.sleep(1)
      r = requests.get(url, headers=headers)
      if r.status_code < 400:
        logger.debug(f"Online (status={r.status_code})")
        return True, True, None
      else:
        error = f"HTTP error code: {r.status_code}"
        logger.error(error)
        return True, False, error
    except Exception as e:
      error = f"Network error: {e}"
      logger.error(error)
      fatal_errors = ['ConnectionError', 'Timeout', 'SSLError']
      if type(e).__name__ in fatal_errors:
        return False, False, error
      else:
        return True, False, error

  def get_report(url, include_ssl_rating=False):
    url = url.strip(' \r\'\"\n').lower()
    alive, online, error = SiteInfo.is_online(url)
    site_info = SiteRecord(url=url, alive=alive, online=online, error=error)
    if not alive or url.startswith('http://'):
      # no point to continue if not alive, or it's HTTP
      return [site_info]
    if not include_ssl_rating:
      # only basic SSL info
      ssl_expiration_info = SSLLabs.get_ssl_expires_in_days(url)[0]
      site_info.ssl_expires = ssl_expiration_info.expires
      if ssl_expiration_info.error:
        site_info.error = ssl_expiration_info.error
      return [site_info]
    # get full SSL report
    final_reports = []
    ssl_rating_info = SSLLabs.get_site_rating(url)
    for record in ssl_rating_info:
      report = copy.copy(site_info)
      report.ip = record.ip
      ssl_expiration_info = SSLLabs.get_ssl_expires_in_days(url, record.ip)[0]
      report.ssl_expires = ssl_expiration_info.expires
      if ssl_expiration_info.error:
        report.error = ssl_expiration_info.error
      report.ssl_rating = record.grade
      if (not report.online) and (record.grade in ['A+', 'A', 'B']):
        # if SSLLabs can analyze, assume it's OK then
        report.online = True
      if record.error:
        # SSL rating error has higher priority
        report.error = record.error
      if record.report:
        report.ssl_report = record.report
      final_reports.append(report)
    return final_reports

class SiteInfoTestCase(unittest.TestCase):
  def test_get_site_report(self):
    report = SiteInfo.get_report("http://us.cloud-learning.net:37828/forecast", True)
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SiteInfo.get_report("https://www.google.com", False)
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SiteInfo.get_report("https://www.google.com", True)
    self.assertEqual(len(report), 2, 'wrong number of records')
    report = SiteInfo.get_report("https://www.google1.com", True)
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SiteInfo.get_report("https://www.indiaglitz.com", False)
    self.assertEqual(len(report), 1, 'wrong number of records')

if 'UNIT_TEST' in os.environ:
  test = SiteInfoTestCase()
  #test.test_get_site_report()

@dataclass
class EmailConfig:
  api_key: str = None
  sender: str = None
  recipients: str = None
  subject_formatter: str = None
  body_template: str = None
  include_attachment: bool = True

@dataclass
class WebHookConfig:
  endpoint: str = None
  content_formatter: str = None

# to start simple, this utility just do one-pass checking (no internal scheduler)
class WebMonitor:
  #########################################
  # Internal helper functions
  #########################################

  def _load_urls(self, url_list_file):
    try:
      urls = []
      with open(url_list_file, 'r') as f:
        lines = f.readlines()
        for line in lines:
          line = line.strip(' \r\'\"\n')
          if not line:
            continue
          if line not in urls:
            urls.append(line)
      return urls
    except Exception as e:
      logger.critical(f"Cannot load site list file: {e}")
      sys.exit(1)

  def _load_email_config(self, emailconfig):
    try:
      settings = EmailConfig()
      settings.api_key = os.environ['SENDGRID_API_KEY'].strip('\" ')
      settings.sender = emailconfig["Sender"].strip('\" ')
      raw_recipients = emailconfig["Recipients"].strip('\" ')
      if raw_recipients:
        white_spaces = ' \n'
        settings.recipients = raw_recipients.translate({ord(i): None for i in white_spaces})
      settings.subject_formatter = emailconfig["Subject"].strip('\" ')
      template_file = emailconfig["BodyTemplate"].strip('\" ')
      if template_file == os.path.basename(template_file):
        template_file = os.path.join(self._config_dir, template_file)
      with open(template_file, 'r') as f:
        settings.body_template = f.read()
      settings.include_attachment = emailconfig.getboolean('Attachment', fallback=True)
      return settings
    except Exception as e:
      logger.error(f"Email configuration is invalid: {e}")
      raise

  def _load_webhook_config(self, webhookconfig):
    try:
      settings = WebHookConfig()
      settings.endpoint = webhookconfig["EndPoint"].strip('\" ')
      settings.content_formatter = webhookconfig["Content"].strip('\" ')
      return settings
    except Exception as e:
      logger.error(f"WebHook configuration is invalid: {e}")
      raise

  def _get_report(self, urls, include_ssl_rating=False):
    full_report = []
    has_down_sites = False
    total = len(urls)
    i = 1
    for url in urls:
      if '://' not in url:
        # assume https
        url = f"https://{url}"
      if not SiteInfo.is_valid_url(url):
        logger.warning(f"Skipping invalid URL: {url}")
        continue
      logger.debug(f"Analyzing site ({i}/{total}): {url}")
      result = SiteInfo.get_report(url, include_ssl_rating)
      i += 1
      if not result[0].online:
        has_down_sites = True
      for record in result:
        full_report.append(record)
    return full_report, has_down_sites

  def _reconfirm_sites(self, report):
    has_down_sites = False
    for record in report:
      if not record.online:
        alive, online, error = SiteInfo.is_online(record.url)
        record.alive = alive
        record.online = online
        record.error = error
        if not online:
          has_down_sites = True
        else:
          logger.info(f"Site is now online: {record.url}")
    return has_down_sites

  # render output based on list of SiteRecord objects
  def _render_template(self, template, report, outputfile=None):
    from jinja2 import Template

    engine = Template(template)
    html = engine.render(sites=report)
    if outputfile:
      with open(outputfile, 'w') as f:
        f.write(html)
    return html

  def _generate_xlsx_report(self, report, outputfile=None):
    import io
    import xlsxwriter

    # Create an in-memory Excel file and add a worksheet
    with io.BytesIO() as output:
      with xlsxwriter.Workbook(output, {'in_memory': True}) as workbook:
        worksheet = workbook.add_worksheet('Site Report')
        # Create header
        bold = workbook.add_format({'bold': True})
        header = [['On',2], ['Grade',4], ['Expires In (days)',4], ['URL',40], ['IP',15], ['Error',40],
                  ['City',10], ['Region',10], ['Country',3]
                 ]
        for i in range(0, len(header)):
          name = header[i][0]
          width = header[i][1]
          worksheet.write(0, i, name, bold)
          worksheet.set_column(i, i, width)
        # Auto-filter
        worksheet.autofilter(0, 0, len(report)-1, len(header)-1)
        # Fill in sheet with report data
        good = workbook.add_format({'bold': True, 'font_color': 'green'})
        bad = workbook.add_format({'bold': True, 'font_color': 'red'})
        row = 1
        for record in report:
          if record.online:
            worksheet.write(row, 0, 'Y', good)
          else:
            worksheet.write(row, 0, 'N', bad)
          if record.ssl_rating and record.ssl_rating.startswith('A'):
            worksheet.write(row, 1, record.ssl_rating, good)
          else:
            worksheet.write(row, 1, record.ssl_rating, bad)
          if record.ssl_expires and record.ssl_expires > 60:
            worksheet.write(row, 2, record.ssl_expires, good)
          else:
            worksheet.write(row, 2, record.ssl_expires, bad)
          if record.ssl_report:
            worksheet.write_url(row, 3, record.ssl_report, string=record.url)
          else:
            worksheet.write(row, 3, record.url)
          worksheet.write(row, 4, record.ip)
          worksheet.write(row, 5, record.error, bad if record.error else None)
          if record.ssl_rating:
            city, region, country = get_url_location(record.url)
            worksheet.write(row, 6, city)
            worksheet.write(row, 7, region)
            worksheet.write(row, 8, country)
          row += 1
      output.seek(0)
      content = output.read()
    if outputfile:
      with open(outputfile, 'wb') as f:
        f.write(content)
    return content

  def _send_email_report(self, report):
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (Mail, MimeType, Attachment, FileContent, FileName,
      FileType, Disposition, ContentId)
    import base64

    try:
      email_config = self._email_settings
      # construct email
      email = Mail()
      email.from_email = email_config.sender
      recipients = email_config.recipients.split(';')
      for recipient in recipients:
        email.add_to(recipient)
      # formatter variables
      today = time.strftime('%Y-%m-%d', time.localtime())
      now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
      mapping = { 'now': now, 'today': today }
      email.subject = email_config.subject_formatter.format_map(mapping)
      email.add_content(self._render_template(email_config.body_template, report), MimeType.html)
      # get attachment
      if email_config.include_attachment:
        content = self._generate_xlsx_report(report)
        attachment = Attachment()
        attachment.file_content = base64.b64encode(content).decode()
        attachment.file_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        attachment.file_name = f"{today}-Site-Report.xlsx"
        attachment.disposition = "attachment"
        email.add_attachment(attachment)
      # send email
      sendgrid = SendGridAPIClient(email_config.api_key)
      r = sendgrid.send(email)
      if r.status_code > 400:
        logger.error(f"SendGrid API failed: error={r.status_code}")
      else:
        logger.info(f"Report was sent successfully.")
    except Exception as e:
      logger.error(f"Failed to send Site SSL Report: {e}")

  def _send_webhook_notice(self, report):
    # get post body
    content = "Following sites may be down:<br>"
    for record in report:
      if not record.online:
        content += f"{record.url} ({record.error})<br>"

    # contruct payload
    webhook_config = self._webhook_settings
    # make string json safe
    content = content.replace('\r', '').replace('\n', '').replace('\\', '\\\\').replace('"', '\\"')
    payload = webhook_config.content_formatter.format(content=content)

    # send over notification
    try:
      logger.debug("Sending webhook notification...")
      headers = {"Content-Type": "application/json"}
      r = requests.post(webhook_config.endpoint, headers=headers, data=payload)
      if r.status_code > 400:
        logger.error(f"Post to webhook failed: {r.status_code}")
    except Exception as e:
      logger.error(f"Post to webhook failed: {error}")

  #########################################
  # Public methods
  #########################################

  def __init__(self, configfile):
    try:
      config = configparser.ConfigParser()
      config.read(configfile)
      self._config_dir = os.path.dirname(configfile)
      self._retry_delay = config.getint("Global", "RetryDelay", fallback=120)
      self._max_retries = config.getint("Global", "MaxRetries", fallback=5)
      self._include_SSL_report = config.getboolean("SSL", "GetSSLReport", fallback=False)
      url_list_file = config["Global"]["URLFile"]
      if url_list_file == os.path.basename(url_list_file):
        url_list_file = os.path.join(self._config_dir, url_list_file)
      self._URLs = self._load_urls(url_list_file)
      self._webhook_settings = None
      self._email_settings = None
      if "WebHook" in config:
        self._webhook_settings = self._load_webhook_config(config["WebHook"])
      if "Email" in config:
        self._email_settings = self._load_email_config(config["Email"])
    except Exception as e:
      logger.error(f"Config file {configfile} is invalid: {e}")
      raise

  def check_sites(self):
    full_report, has_down_sites = self._get_report(self._URLs, self._include_SSL_report)
    # reconfirm failed sites
    retries = 0
    while has_down_sites and retries < self._max_retries:
      retries += 1
      logger.info(f"Wait some time and retry failed sites (retry #{retries})")
      time.sleep(self._retry_delay)
      has_down_sites = self._reconfirm_sites(full_report)
    # sort list to move items with error to front
    if len(full_report) > 0:
      full_report.sort(key=lambda i: i.error if i.error else '', reverse=True)
      full_report.sort(key=lambda i: i.ssl_rating if i.ssl_rating else 'Unknown', reverse=True)
      full_report.sort(key=lambda i: i.online)
    # send email if ssl rating included, or has failed sites
    if self._include_SSL_report or has_down_sites:
      if self._email_settings:
        self._send_email_report(full_report)
      if self._webhook_settings:
        self._send_webhook_notice(full_report)
      # also archive the report locally, in case email gets lost
      now = datetime.datetime.now()
      archive_folder = '/tmp/dropbox_archive'
      if not os.path.exists(archive_folder):
        os.makedirs(archive_folder)
      report_file = f"{archive_folder}/Site-Report-{now.strftime('%Y-%m-%d_%H_%M_%S')}.xlsx"
      self._generate_xlsx_report(full_report, report_file)

class WebMonitorTestCase(unittest.TestCase):
  def test_webmonitor_report(self):
    urls = ['https://www.google.com', 'https://www.google1.com']
    report, has_down = WebMonitor.get_report(urls, True)
    self.assertEqual(len(report), 2, 'wrong number of records')
    WebMonitor.generate_xlsx_report(report, '/tmp/000.xlsx')
    html = WebMonitor.generate_html_body(report, '/tmp/000.html')
    WebMonitor.send_email_report(report)

if 'UNIT_TEST' in os.environ:
  test = WebMonitorTestCase()
  test.test_webmonitor_report()

########################################
# CLI interface
########################################

def check_sites(args):
  monitor = WebMonitor(args.config)
  monitor.check_sites()

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
  CLI_config = { 'func':check_sites, 'arguments': [
    {'name':'config', 'help':'Config file for monitor'} 
    ]}
  try:
   parser = CLIParser.get_parser(CLI_config)
   CLIParser.run(parser)
  except Exception as e:
   logger.error(f"Exception happened: {e}")
   sys.exit(1)
