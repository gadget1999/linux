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

@dataclass
class SSLRecord:
  url: str
  report: str = None
  ip: str = None
  grade: str = None
  expires: str = None
  error: str = None

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
  ip: str = None
  error: str = None
  ssl_expires: str = None
  ssl_rating: str = None

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
      r = requests.get(url)
      if r.status_code < 500:
        logger.debug(f"Online (status={r.status_code})")
        return True, True, None
      else:
        error = f"HTTP error code: {r.status_code}"
        logger.error(error)
        return True, False, error
    except Exception as e:
      error = f"Network error: {e}"
      logger.error(error)
      return False, False, error

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
      if record.error:
        # SSL rating error has higher priority
        report.error = record.error
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
  api_key: str
  sender: str
  recipients: str

# to start simple, this utility just do one-pass checking (no internal scheduler)
class WebMonitor:
  __html_SSL_report_template = """
<html>
 <head>
  <title>Web Site Report</title>
  <style>
   table {
    font-family: arial, sans-serif;
    table-layout: auto;
    border-collapse: collapse;
    width: 100%;
   }
   td, th {
    border: 1px solid #dddddd;
    text-align: left;
    padding: 2px;
   }
   tr:nth-child(even) {
    background-color: #dddddd;
   }
  </style>
 </head>
 <body>
  <p>
  SSL rating report from API provided by: https://www.ssllabs.com/ssltest/index.html
  </p>
  <table>
    <tr>
     <th>Online</th>
     <th>Grade</th>
     <th>Expires (days)</th>
     <th>URL</th>
     <th>IP</th>
     <th>Error</th>
    </tr>
    {%- for site in sites %}
    <tr>
     <td>
      {% if site.online %}
      <b style=\"color:green;\">Y</b>
      {% else %}
      <b style=\"color:red;\">N</b>
      {% endif %}
     </td>
     <td>
      {% if site.ssl_rating and site.ssl_rating.startswith('A') %}
      <b style=\"color:green;\">{{ site.ssl_rating }}</b>
      {% else %}
      <b style=\"color:red;\">{{ site.ssl_rating if site.ssl_rating }}</b>
      {% endif %}
     </td>
     <td>
      {% if site.ssl_expires and (site.ssl_expires|int < 60) %}
      <b style=\"color:red;\">{{ site.ssl_expires }}</b>
      {% else %}
      {{ site.ssl_expires if site.ssl_expires }}
      {% endif %}
     </td>
     <td>
      <a href="{{ site.report }}">{{ site.url }}</a>
     </td>
     <td>
      {{ site.ip if site.ip }}
     </td>
     <td>
      {{ site.error if site.error }}
     </td>
    </tr>
    {%- endfor %}
  </table>
 </body>
</html>
"""

  def __load_urls(url_list_file):
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

  def __load_email_config():
    try:
      api_key = os.environ['SENDGRID_API_KEY'].strip('\" ')
      sender = os.environ['MONITOR_SENDER'].strip('\" ')
      white_spaces = ' \n'
      clean_string = os.environ['MONITOR_RECIPIENTS'].translate({ord(i): None for i in white_spaces})
      recipients = clean_string.split(';')
      return EmailConfig(api_key=api_key, sender=sender, recipients=recipients)
    except Exception as e:
      logger.error(f"Email configuration incomplete: {e}")
      return None

  def generate_html_body(report, outputfile=None):
    from jinja2 import Template

    engine = Template(WebMonitor.__html_SSL_report_template)
    html = engine.render(sites=report)
    if outputfile:
      with open(outputfile, 'w') as f:
        f.write(html)
    return html

  def generate_xlsx_report(report, outputfile=None):
    import io
    import xlsxwriter

    # Create an in-memory Excel file and add a worksheet
    with io.BytesIO() as output:
      with xlsxwriter.Workbook(output, {'in_memory': True}) as workbook:
        worksheet = workbook.add_worksheet('Site Report')
        # Create header
        bold = workbook.add_format({'bold': True})
        header = [['On',2], ['Grade',4], ['Expires In (days)',4], ['URL',40], ['IP',15],
                  ['City',10], ['Region',10], ['Country',3],
                  ['Error',40] ]
        for i in range(0, len(header)):
          name = header[i][0]
          width = header[i][1]
          worksheet.write(0, i, name, bold)
          worksheet.set_column(i, i, width)
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
          worksheet.write(row, 3, record.url)
          worksheet.write(row, 4, record.ip)
          city, region, country = get_url_location(record.url)
          worksheet.write(row, 5, city)
          worksheet.write(row, 6, region)
          worksheet.write(row, 7, country)
          worksheet.write(row, 8, record.error, bad if record.error else None)
          row += 1
      output.seek(0)
      content = output.read()
    if outputfile:
      with open(outputfile, 'wb') as f:
        f.write(content)
    return content

  def send_email_report(report):
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (Mail, MimeType, Attachment, FileContent, FileName,
      FileType, Disposition, ContentId)
    import base64

    email_config = WebMonitor.__load_email_config()
    if not email_config or not report:
      return
    try:
      # construct email
      email = Mail()
      email.from_email = email_config.sender
      for recipient in email_config.recipients:
        email.add_to(recipient)
      today = time.strftime('%Y-%m-%d', time.localtime())
      email.subject = f"[{today}] Site Monitoring Report"
      email.add_content(WebMonitor.generate_html_body(report), MimeType.html)
      # get attachment
      content = WebMonitor.generate_xlsx_report(report)
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
    except Exception as e:
      logger.error(f"Failed to send Site SSL Report: {e}")

  def __reconfirm_sites(report):
    logger.info("Wait some time and retry failed sites.")
    time.sleep(120)
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

  def get_report(urls, include_ssl_rating=False):
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

  def check_sites(urls, include_ssl_rating=False):
    full_report, has_down_sites = WebMonitor.get_report(urls, include_ssl_rating)
    # reconfirm failed sites
    if has_down_sites:
      has_down_sites = WebMonitor.__reconfirm_sites(full_report)
    # send email if ssl rating included, or has failed sites
    if include_ssl_rating or has_down_sites:
      WebMonitor.send_email_report(full_report)

  def check_sites_in_file(url_list_file, include_ssl_rating=False):
    urls = WebMonitor.__load_urls(url_list_file)
    WebMonitor.check_sites(urls, include_ssl_rating)

class WebMonitorTestCase(unittest.TestCase):
  def test_webmonitor_report(self):
    urls = ['https://www.google.com', 'https://www.google1.com']
    report, has_down = WebMonitor.get_report(urls, True)
    WebMonitor.generate_xlsx_report(report, '/tmp/000.xlsx')
    WebMonitor.send_email_report(report)
    self.assertEqual(len(report), 3, 'wrong number of records')
    report, has_down = WebMonitor.get_report(urls, True)
    self.assertEqual(len(report), 4, 'wrong number of records')
    html = WebMonitor.generate_html_body(report, '/tmp/000.html')
    WebMonitor.send_email_report(report)

if 'UNIT_TEST' in os.environ:
  test = WebMonitorTestCase()
  test.test_webmonitor_report()

########################################
# CLI interface
########################################

def check_sites(args):
  logger.debug(f"CMD - Check sites in [{args.file}] (include SSL grade: {args.get_ssl_grade})")
  WebMonitor.check_sites_in_file(args.file, args.get_ssl_grade)

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
    {'name':'file', 'help':'File contains list of sites'}, 
    {'name':'--get_ssl_grade', 'help':'Include SSL rating', 'action':'store_true'}
    ]}
  try:
   parser = CLIParser.get_parser(CLI_config)
   CLIParser.run(parser)
  except Exception as e:
   logger.error(f"Exception happened: {e}")
   sys.exit(1)
