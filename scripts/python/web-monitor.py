#!/usr/bin/env python3

import os, sys
import json
import time, datetime
import dateutil.parser as parser
# for struct-like class
import copy
from dataclasses import dataclass
# for web APIs
import socket, ipaddress
import requests
from urllib.parse import urlparse
# for unittest
import unittest
# for reporting
from jinja2 import Template # HTML report
from openpyxl import Workbook, load_workbook # read Excel URL lists
import io, xlsxwriter # Excel report
from influxdb import InfluxDBHelper # InfluxDB history
# for email
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (Mail, MimeType, Attachment, FileContent, FileName,
  FileType, Disposition, ContentId)
import base64 # for attachment
# for Azure DNS glitch (use custom DNS to confirm)
import dns.resolver
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ["9.9.9.9"]
# for logging and CLI arguments parsing
import configparser
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36"
POSSIBLE_DNS_GLITCH = "Name or service not known"

def get_latest_user_agent():
  # it's OK to read global variable within a function
  # but must use 'global' if need to change its value
  global USER_AGENT
  try:
    url = "https://jnrbsn.github.io/user-agents/user-agents.json"
    r = requests.get(url)
    if r.status_code >= 400:
      logger.warning(f"Failed to get latest user agent list. (status={r.status_code})")
      return
    user_agent = r.json()[0]
    if user_agent.startswith("Mozilla/") and user_agent != USER_AGENT:
      logger.info(f"Found a newer user agent: {user_agent}")
      USER_AGENT = user_agent
  except Exception as e:
    logger.warning(f"Failed to get the latest user agent list. ({e})")

# Some times requests or socket get 'Name or service not known' incorrectly, can use a different DNS server to confirm
def is_host_reachable(url):
  try:
    parsed_uri = urlparse(url)
    host = parsed_uri.hostname if parsed_uri.hostname else url
    port = parsed_uri.port if parsed_uri.port else 443
    answers = dns.resolver.resolve(host, 'A')
    if not answers:
      logger.error(f"Custom DNS lookup failed for {url}")
      return False
    # verify each IP from results
    for answer in answers:
      ip = answer.address
      try:
        with socket.create_connection((ip, port), timeout=10) as conn:
          logger.info(f"{url} IP address is reachable: {ip}")
      except:
        logger.info(f"{url} IP address is NOT reachable: {ip}")
        return False
    # now all IP addresses are verified, consider as OK for now
    return True
  except Exception as e:
    logger.error(f"Custom DNS lookup failed for {url}: {e}")
    return False

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
    headers = {
      "User-Agent": USER_AGENT
    }
    r = requests.get(url, headers=headers)
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
    headers = {
      "User-Agent": USER_AGENT
    }
    r = requests.get(analyze_endpoint, params=params, headers=headers)
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
      headers = {
        "User-Agent": USER_AGENT
      }
      r = requests.get(info_endpoint, headers=headers)
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
    for i in range(0, 20):
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
        logger.debug(f"Checking SSL rating for {url}...")
        result = SSLLabs.__analyze_server(url)
      except APIThrottlingException:
        # retry after a while if throttled
        logger.info("Sleeping for a while to avoid further throttling.")
        time.sleep(1000)
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

### SSLLabs reports is slow and subject to heavy throttling, switching to local scan based on TestSSL.sh
class TestSSL_sh:
  def set_config(local_scanner, openssl_path, show_progress):
    TestSSL_sh._local_scanner = local_scanner
    TestSSL_sh._openssl_scanner = openssl_path
    TestSSL_sh._show_progress = show_progress

  def __exec_cmd(args):
    time.sleep(15) # adding some delay to reduce server impact
    import subprocess
    if TestSSL_sh._show_progress:
      run_result = subprocess.run(args.split())
    else:
      run_result = subprocess.run(args.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run_result.stderr:
      logger.error(f"Error: {run_result.stderr}")

  def get_site_rating(url):
    import random
    ratings = []
    try:
      logger.debug(f"Checking SSL rating for {url}... (Testssl.sh)")
      # execute testssl.sh and get json output
      jsonfile = f"/tmp/{random.randint(1, 1000000)}.json"
      args = f"{TestSSL_sh._local_scanner} " \
             f"--openssl={TestSSL_sh._openssl_scanner} --fast --ip one " \
             f"--quiet --overwrite --jsonfile-pretty {jsonfile} " \
             f"{url}"
      TestSSL_sh.__exec_cmd(args)
      cmd_json_out = {}
      with open(jsonfile, "r") as f:
        cmd_json_out = json.load(f)
      os.remove(jsonfile)
      # parse json file
      list_ratings = cmd_json_out['scanResult'][0]['rating']
      json_rating = next(x for x in list_ratings if x["id"] == "overall_grade")
      grade = json_rating["finding"]
      logger.info(f"Grade: {grade} [{url}]")
      # assemble report
      parsed_uri = urlparse(url)
      report_url = f"https://www.ssllabs.com/ssltest/analyze.html?d={parsed_uri.hostname}&hideResults=on"
      rating = SSLRecord(url=url, report=report_url)
      rating.grade = grade
      ratings.append(rating)
      return ratings
    except Exception as e:
      logger.error(f"{e}")
      return [SSLRecord(url=url, grade='Error', error=f"{e}")]

@dataclass
class SSLScannerConfig:
  generate_rating: bool = False
  use_ssllabs: bool = False
  local_scanner: str = None
  openssl_path: str = None
  show_progress: bool = False

class SSLReport:
  def set_config(settings):
    SSLReport._settings = settings
    if not settings.use_ssllabs:
      TestSSL_sh.set_config(settings.local_scanner, settings.openssl_path, settings.show_progress)

  def should_get_rating():
    return SSLReport._settings.generate_rating

  def get_site_rating(url):
    if (SSLReport._settings.use_ssllabs):
      return SSLLabs.get_site_rating(url)
    else :
      return TestSSL_sh.get_site_rating(url)

  def __get_ssl_expiration_date(host, ip=None, port=443):
    import ssl

    try:
      if not ip:
        ip = host
      if not port:
        port = 443
      #logger.debug(f"Getting SSL certificate info: {ip}:{port}")
      context = ssl.create_default_context()
      with socket.create_connection((ip, port)) as sock:
        with context.wrap_socket(sock, server_hostname=host) as ssock:
          cert_info = ssock.getpeercert()
          ssl_date_fmt = r'%b %d %H:%M:%S %Y %Z'
          expire_time = datetime.datetime.strptime(cert_info['notAfter'], ssl_date_fmt)
          logger.debug(f"SSL expiration date: {expire_time.strftime('%Y-%m-%d')}")          
          return expire_time, None
    except Exception as e:
      error = f"Failed to get expiration date for {host}: {e}"
      logger.error(error)
      if "Temporary failure" in error:
        error = None
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
      expires, error = SSLReport.__get_ssl_expiration_date(host, ip, port)
      if error:
        # ignore once if temp DNS glitch "Name or service not known" but host reachable
        if (POSSIBLE_DNS_GLITCH in error) and is_host_reachable(url):
          continue
        result.error = error
      elif expires:
        expires_in_days = (expires - datetime.datetime.now()).days
        result.expires = expires_in_days
        if (expires_in_days < 7):
          result.error = "Certificate will expire soon!"
          logger.error(result.error)
      results.append(result)
    if not results:
      # if comes here, means all DNS glitches
      result = SSLRecord(url=url, ip=ip)
      result.error = "Temp DNS error"
      results.append(result)
    return results

class SSLLabsTestCase(unittest.TestCase):
  def test_get_ssl_ratings(self):
    rating = SSLReport.get_site_rating("https://www.google.com")
    self.assertEqual(len(rating), 2, 'wrong number of records')
    rating = SSLReport.get_site_rating("https://www.google1.com")
    self.assertEqual(len(rating), 1, 'wrong number of records')
  def test_get_ssl_expiration(self):
    report = SSLReport.get_ssl_expires_in_days("https://www.indiaglitz.com", check_endpoints=True)
    self.assertEqual(len(report), 4, 'wrong number of records')
    report = SSLReport.get_ssl_expires_in_days("https://www.indiaglitz.com")
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SSLReport.get_ssl_expires_in_days("https://www.google1.com")
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
  response_time: int = 0
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

  def get_status(url, allow_retry=True):
    status = SiteRecord(url=url)
    # return alive (if reachable), online (if functional) and error if any
    # by default alive and online status will be False unless explicitly set to True
    try:
      #logger.debug(f"Checking [{url}] status...")
      time.sleep(1)
      t_start = time.perf_counter_ns()
      headers = {
        "Accept-Language": "en-US,en;q=0.5",
        "User-Agent": USER_AGENT
      }
      r = requests.get(url, headers=headers, timeout=120)
      r.close()
      t_stop = time.perf_counter_ns()
      t_elapsed_ms = int((t_stop - t_start) / 1000000)
      status.response_time = t_elapsed_ms
      if r.status_code < 400:
        logger.debug(f"Online (status={r.status_code}, time={t_elapsed_ms}ms)")
        if (t_elapsed_ms > 10000):
          logger.error(f"{url} response time too long: {t_elapsed_ms}ms")
        status.alive = True
        status.online = True
      elif "maintenance" in r.text:
        status.alive = True
        status.online = True
        logger.info(f"{url} is under maintenance: {r.text}")
      else:
        status.error = f"HTTP error code: {r.status_code}"
        logger.error(f"{url} failed: {status.error}")
        status.alive = True
      return status
    except Exception as e:
      error_type = type(e).__name__
      error_msg = f"{e}"
      if (POSSIBLE_DNS_GLITCH in error_msg):
        if allow_retry:
          # retry once for DNS error
          time.sleep(15)
          return SiteInfo.get_status(url, False)
        logger.error(f"{url} DNS error: {POSSIBLE_DNS_GLITCH}")
        # retry still failed, try to ping IP directly (this may not be accurate for sites using reverse proxy)
        if is_host_reachable(url):
          # ignore once since requests DNS is at fault, but hard to let it use alternative DNS
          status.alive = True
          status.online = True
          return status
      else:
        logger.error(f"{url} failed: {error_type} - {error_msg}")
      status.error = f"{error_type}: {error_msg}"
      if error_type not in ['ConnectionError', 'Timeout', 'SSLError']:
        status.alive = True
      return status

  def is_blocked(url):
    try:
      time.sleep(1)
      headers = {
        "Accept-Language": "en-US,en;q=0.5",
        "User-Agent": USER_AGENT
      }
      r = requests.get(url, headers=headers)
      r.close()
      if r.status_code < 400:
        logger.error(f"Online (status={r.status_code}) --> Unexpected!")
        return False
      else:
        logger.debug(f"HTTP error code: {r.status_code} --> Expected")
        return True
    except Exception as e:
      logger.debug(f"Network error: {e} --> Expected")
      return True

  def get_report(url, include_ssl_rating=False):
    url = url.strip(' \r\'\"\n').lower()
    site_info = SiteInfo.get_status(url)
    if not site_info.alive \
       or url.startswith('http://') \
       or not include_ssl_rating:
      # no point to continue if not alive, or it's HTTP, or no need for SSL info
      return [site_info]
    # basic SSL info
    ssl_expiration_info = SSLReport.get_ssl_expires_in_days(url)[0]
    site_info.ssl_expires = ssl_expiration_info.expires
    if ssl_expiration_info.error:
      site_info.error = ssl_expiration_info.error
    if not SSLReport.should_get_rating():
      return [site_info]
    # get full SSL report
    final_reports = []
    ssl_rating_info = SSLReport.get_site_rating(url)
    for record in ssl_rating_info:
      report = copy.copy(site_info)
      report.ip = record.ip
      ssl_expiration_info = SSLReport.get_ssl_expires_in_days(url, record.ip)[0]
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

@dataclass
class InfluxDBConfig:
  endpoint: str = None
  token: str = None
  tenant: str = None
  bucket: str = None

# to start simple, this utility just do one-pass checking (no internal scheduler)
class WebMonitor:
  #########################################
  # Internal helper functions
  #########################################

  def is_future_time(self, time):
    try:
      if type(time) is datetime.datetime:
        test_time = time
      else:
        test_time = parser.parse(time)
      return True if (test_time > datetime.datetime.now()) else False
    except Exception as e:
      logger.error(f"Failed to parse maintenance time [{time}]: {e}")
      return False

  def _load_urls_from_xlsx(self, filepath):
    try:
      urls = []
      workbook = load_workbook(filepath)
      for sheet in workbook.worksheets:
        url_count = 0
        urls_in_sheet = []
        for row in sheet.rows:
          line = row[0].value
          if not line:
            break
          line = line.lower().strip(' \r\'\"\n')
          if line.startswith(("http://", "https://")):
            # also check if there is a maintenance
            ignore_until = row[1].value
            if ignore_until and self.is_future_time(ignore_until):
              logger.debug(f"{line} is under maintenance until {ignore_until}")
              continue
            if self._include_SSL_grade and len(row) > 2:
              # check if SSL report is required for the URL
              include_ssl_grade = row[2].value
              if include_ssl_grade is None or ("yes" not in include_ssl_grade.lower()):
                continue
            urls_in_sheet.append(line)
            url_count += 1
        # Excel only logic: if there are URLs in 'Internal' tab, record them separately
        if sheet.title == 'Internal':
          logger.debug(f"Found {url_count} INTERNAL URLs")
          self._URLS_BLOCKED = urls_in_sheet
        else:
          logger.debug(f"Sheet [{sheet.title}]: found {url_count} URLs")
          urls.extend(urls_in_sheet)
      workbook.close()
      return urls
    except Exception as e:
      logger.critical(f"Cannot load site list file [{filepath}]: {e}")
      sys.exit(1)

  def _load_urls_from_txt(self, filepath):
    try:
      urls = []
      with open(filepath, 'r') as f:
        lines = f.readlines()
        for line in lines:
          line = line.strip(' \r\'\"\n')
          if not line:
            continue
          if line not in urls:
            urls.append(line)
      return urls
    except Exception as e:
      logger.critical(f"Cannot load site list file [{filepath}]: {e}")
      sys.exit(1)

  def _load_urls(self, filepath):
    if filepath.lower().endswith('.xlsx'):
      return self._load_urls_from_xlsx(filepath)
    else:
      return self._load_urls_from_txt(filepath)

  def _load_email_config(self, config, section):
    try:
      if section not in config: return None
      sectionConfig = config[section]
      settings = EmailConfig()
      settings.api_key = os.environ['SENDGRID_API_KEY'].strip('\" ')
      settings.sender = sectionConfig["Sender"].strip('\" ')
      raw_recipients = sectionConfig["Recipients"].strip('\" ')
      if raw_recipients:
        white_spaces = ' \n'
        settings.recipients = raw_recipients.translate({ord(i): None for i in white_spaces})
      settings.subject_formatter = sectionConfig["Subject"].strip('\" ')
      template_file = sectionConfig["BodyTemplate"].strip('\" ')
      if template_file == os.path.basename(template_file):
        template_file = os.path.join(self._config_dir, template_file)
      with open(template_file, 'r') as f:
        settings.body_template = f.read()
      settings.include_attachment = sectionConfig.getboolean('Attachment', fallback=True)
      return settings
    except Exception as e:
      logger.error(f"Email configuration is invalid: {e}")
      raise

  def _load_webhook_config(self, config, section):
    try:
      if section not in config: return None
      sectionConfig = config[section]
      settings = WebHookConfig()
      settings.endpoint = sectionConfig["EndPoint"].strip('\" ')
      settings.content_formatter = sectionConfig["Content"].strip('\" ')
      return settings
    except Exception as e:
      logger.error(f"WebHook configuration is invalid: {e}")
      raise

  def _load_influxdb_config(self, config, section):
    try:
      if section not in config: return None
      sectionConfig = config[section]
      settings = InfluxDBConfig()
      settings.endpoint = sectionConfig["InfluxDBAPIEndPoint"].strip('\" ')
      settings.token = sectionConfig["InfluxDBAPIToken"].strip('\" ')
      settings.tenant = sectionConfig["InfluxDBTenant"].strip('\" ')
      settings.bucket = sectionConfig["InfluxDBBucket"].strip('\" ')
      return settings
    except Exception as e:
      logger.error(f"InfluxDB configuration is invalid: {e}")
      raise

  def _load_sslscanner_config(self, sslscannerconfig):
    try:
      settings = SSLScannerConfig()
      settings.generate_rating = sslscannerconfig.getboolean("GenerateSSLRating", fallback=False)
      settings.use_ssllabs = sslscannerconfig.getboolean("UseSSLLabs", fallback=False)
      if not settings.use_ssllabs:
        settings.local_scanner = sslscannerconfig["LocalScanner"].strip('\" ')
        settings.openssl_path = sslscannerconfig["OpenSSLPath"].strip('\" ')
        settings.show_progress = sslscannerconfig.getboolean("ShowProgress", fallback=False)
      return settings
    except Exception as e:
      logger.error(f"SSLScanner configuration is invalid: {e}")
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

  def _get_report_blocked(self, urls):
    report_blocked = []
    total = len(urls)
    i = 1
    for url in urls:
      if '://' not in url:
        # assume https
        url = f"https://{url}"
      if not SiteInfo.is_valid_url(url):
        logger.warning(f"Skipping invalid URL: {url}")
        continue
      logger.debug(f"Analyzing INTERNAL site ({i}/{total}): {url}")
      i += 1
      if SiteInfo.is_blocked(url):
        continue
      # if online, means mis-configuration
      record = SiteRecord(url=url, alive=True, online=True, error="Internal URL not blocked.")
      report_blocked.append(record)
    return report_blocked

  def _reconfirm_sites(self, report):
    has_down_sites = False
    for record in report:
      if not record.online:
        status = SiteInfo.get_status(record.url)
        record.alive = status.alive
        record.online = status.online
        record.error = status.error
        if not status.online:
          has_down_sites = True
        else:
          logger.info(f"Site is now online: {record.url}")
    return has_down_sites

  # render output based on list of SiteRecord objects
  def _render_template(self, template, report, outputfile=None):
    engine = Template(template)
    html = engine.render(sites=report)
    if outputfile:
      with open(outputfile, 'w') as f:
        f.write(html)
    return html

  def _generate_xlsx_report(self, report, outputfile=None):
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
          # skip getting location as it's no longer needed
          if record.ssl_rating and False:
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
      headers = {
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT
      }
      r = requests.post(webhook_config.endpoint, headers=headers, data=payload)
      if r.status_code > 400:
        logger.error(f"Post to webhook failed: {r.status_code}")
    except Exception as e:
      logger.error(f"Post to webhook failed: {e}")

  def _store_influxdb_report(self, report):
    influxdb_settings = InfluxDBConfig(
      endpoint=self._influxdb_settings.endpoint,
      token=self._influxdb_settings.token,
      tenant=self._influxdb_settings.tenant,
      bucket=self._influxdb_settings.bucket
      )
    influxdb_writer = InfluxDBHelper(influxdb_settings)
    logger.debug("Storing metrics into InfluxDB...")
    for record in report:
      parsed_uri = urlparse(record.url)
      data = []
      if not record.error:
        data.append(("Response_Time", record.response_time))
      data.append(("Offline", 0 if record.online else 1))
      try:
        influxdb_writer.report_data_list("Metrics", parsed_uri.hostname, data)
      except Exception as e:
        logger.error(f"Failed to store InfluxDB record: {parsed_uri.hostname}: {e}")


  #########################################
  # Public methods
  #########################################

  def __init__(self, configfile):
    try:
      if not os.path.isfile(configfile):
        raise Exception(f"Config file [{configfile}] does not exist.")
      config = configparser.ConfigParser()
      config.read(configfile)
      self._config_dir = os.path.dirname(configfile)
      self._retry_delay = config.getint("Global", "RetryDelay", fallback=120)
      self._max_retries = config.getint("Global", "MaxRetries", fallback=5)
      self._include_SSL_report = config.getboolean("SSL", "GetSSLReport", fallback=False)
      self._include_SSL_grade = config.getboolean("SSL", "GenerateSSLRating", fallback=False)
      url_list_file = config["Global"]["URLFile"]
      if url_list_file == os.path.basename(url_list_file):
        url_list_file = os.path.join(self._config_dir, url_list_file)
      self._URLs = self._load_urls(url_list_file)
      self._email_settings = self._load_email_config(config, "Email")
      self._influxdb_settings = self._load_influxdb_config(config, "InfluxDB")
      self._webhook_settings = self._load_webhook_config(config, "WebHook")
      if self._include_SSL_report:
        SSLReport.set_config(self._load_sslscanner_config(config["SSL"]))
    except Exception as e:
      logger.error(f"Config file {configfile} is invalid: {e}")
      raise

  def check_sites(self):
    full_report, has_down_sites = self._get_report(self._URLs, self._include_SSL_report)
    # reconfirm failed sites
    retries = 0
    while has_down_sites and retries < self._max_retries:
      retries += 1
      logger.info(f"Wait some time and retry (#{retries}) failed sites.")
      time.sleep(self._retry_delay)
      has_down_sites = self._reconfirm_sites(full_report)
    if len(full_report) == 0:
      logger.error(f"Site report list is empty.")
      return
    # check if any of blocked sites are accessible
    if '_URLS_BLOCKED' in dir(self):
      full_report.extend(self._get_report_blocked(self._URLS_BLOCKED))
    # sort list to move items with error to front
    full_report.sort(key=lambda i: i.error if i.error else '', reverse=True)
    full_report.sort(key=lambda i: i.ssl_rating if i.ssl_rating else 'Unknown', reverse=True)
    full_report.sort(key=lambda i: i.online)
    full_report.sort(key=lambda i: i.ssl_expires if i.ssl_expires else 0)
    num_errors = sum(1 for x in full_report if x.error)
    # always record metrics stats
    if self._influxdb_settings:
      self._store_influxdb_report(full_report)
    # send email if ssl rating included, or has failed sites, or has errors
    if self._include_SSL_report or has_down_sites or num_errors > 0:
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
      if num_errors > 0:
        logger.error(f"Scan completed: {num_errors} of {len(full_report)} URLs have errors.")
      else:
        logger.info(f"Scan completed: no errors for {len(full_report)} URLs.")

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
if (__name__ == '__main__') and ('UNIT_TEST' not in os.environ):
  CLI_config = { 'func':check_sites, 'arguments': [
    {'name':'config', 'help':'Config file for monitor'} 
    ]}
  CLIParser.run(CLI_config)
