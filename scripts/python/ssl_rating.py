#!/usr/bin/env python3
"""
SSL Rating Module
Handles SSL certificate analysis using either SSLLabs API or local TestSSL.sh scanner

Configuration Examples:

Dictionary-based configuration (recommended):
  ssl_config = {
    "generate_rating": True,
    "use_ssllabs": False,  # True for SSLLabs API, False for local TestSSL.sh
    "local_scanner": "/opt/testssl.sh/testssl.sh",
    "openssl_path": "/usr/bin/openssl", 
    "show_progress": True
  }
  
  # Load configuration
  from ssl_rating import load_ssl_config_from_dict, SSLReport
  settings = load_ssl_config_from_dict(ssl_config)
  SSLReport.set_config(settings)

ConfigParser section (backward compatibility):
  [SSL]
  GenerateSSLRating=yes
  UseSSLLabs=no
  LocalScanner=/opt/testssl.sh/testssl.sh
  OpenSSLPath=/usr/bin/openssl
  ShowProgress=yes
"""

import os
import json
import time
import datetime
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import urlparse
import requests
import web_util
from common import Logger

logger = Logger.getLogger()

# Global variables from main module
POSSIBLE_DNS_GLITCH = "Name or service not known"

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
  """SSLLabs API client for SSL certificate analysis"""
  
  @staticmethod
  def __analyze_api_call(params):
    analyze_endpoint = 'https://api.ssllabs.com/api/v3/analyze'
    # force 2 seconds sleep to avoid hitting 529 (newAssessmentCoolOff)
    time.sleep(2)
    headers = {
      "User-Agent": web_util.get_user_agent()
    }
    r = requests.get(analyze_endpoint, params=params, headers=headers)
    if r.status_code == 429 or r.status_code == 529:
      raise APIThrottlingException(f"SSLLabs API throttled: error={r.status_code}")
    elif r.status_code > 400:
      raise Exception(f"SSLLabs API failed: error={r.status_code}")
    return r.json()

  @staticmethod
  def __track_server_load():
    try:
      info_endpoint = 'https://api.ssllabs.com/api/v3/info'
      # force 2 seconds sleep to avoid hitting 529 (newAssessmentCoolOff)
      time.sleep(2)
      headers = {
        "User-Agent": web_util.get_user_agent()
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

  @staticmethod
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

  @staticmethod
  def get_site_rating(url):
    """Get SSL rating from SSLLabs for a given URL"""
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
        if web_util.is_ipv6(rating.ip):
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

class TestSSL_sh:
  """Local TestSSL.sh scanner for SSL certificate analysis"""
  
  @staticmethod
  def set_config(local_scanner, openssl_path, show_progress):
    TestSSL_sh._local_scanner = local_scanner
    TestSSL_sh._openssl_scanner = openssl_path
    TestSSL_sh._show_progress = show_progress

  @staticmethod
  def __exec_cmd(args):
    time.sleep(15) # adding some delay to reduce server impact
    import subprocess
    if TestSSL_sh._show_progress:
      run_result = subprocess.run(args.split())
    else:
      run_result = subprocess.run(args.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if run_result.stderr:
      logger.error(f"Error: {run_result.stderr}")

  @staticmethod
  def get_site_rating(url):
    """Get SSL rating using local TestSSL.sh scanner"""
    import random
    ratings = []
    try:
      logger.debug(f"Checking SSL rating for {url}... (Testssl.sh)")
      # execute testssl.sh and get json output
      jsonfile = f"/tmp/{random.randint(1, 1000000)}.json"
      args = f"{TestSSL_sh._local_scanner} " \
             f"--openssl={TestSSL_sh._openssl_scanner} --fast --ip one " \
             f"--quiet --jsonfile-pretty {jsonfile} " \
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
  """Configuration for SSL scanner"""
  generate_rating: bool = False
  use_ssllabs: bool = False
  local_scanner: str = None
  openssl_path: str = None
  show_progress: bool = False

class SSLReport:
  """Main SSL reporting class that coordinates between different scanners"""
  
  @staticmethod
  def set_config(settings):
    SSLReport._settings = settings
    if not settings.use_ssllabs:
      TestSSL_sh.set_config(settings.local_scanner, settings.openssl_path, settings.show_progress)

  @staticmethod
  def should_get_rating():
    return SSLReport._settings.generate_rating

  @staticmethod
  def get_site_rating(url):
    """Get SSL rating using configured scanner (SSLLabs or TestSSL.sh)"""
    if (SSLReport._settings.use_ssllabs):
      return SSLLabs.get_site_rating(url)
    else :
      return TestSSL_sh.get_site_rating(url)

  @staticmethod
  def __get_ssl_expiration_date(host, ip=None, port=443):
    """Get SSL certificate expiration date"""
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

  @staticmethod
  def get_ssl_expires_in_days(url, ip=None, check_endpoints=False, get_ip_addresses_func=None, is_host_reachable_func=None):
    """Get SSL certificate expiration information"""
    parsed_uri = urlparse(url)
    host = parsed_uri.hostname
    port = parsed_uri.port
    if ip:
      # only scan specified endpoint
      addresses = [ip]
    elif check_endpoints and get_ip_addresses_func:
      # check all endpoints
      addresses, error = get_ip_addresses_func(host, port)
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
        if (POSSIBLE_DNS_GLITCH in error) and is_host_reachable_func and is_host_reachable_func(url):
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

def create_ssl_config(config_dict):
  """Create SSL scanner configuration from dictionary"""
  settings = SSLScannerConfig()
  settings.generate_rating = config_dict.get("generate_rating", False)
  settings.use_ssllabs = config_dict.get("use_ssllabs", False)
  
  if not settings.use_ssllabs:
    settings.local_scanner = config_dict.get("local_scanner", "").strip('\" ')
    settings.openssl_path = config_dict.get("openssl_path", "").strip('\" ')
    settings.show_progress = config_dict.get("show_progress", False)

    if settings.generate_rating and \
      ((not settings.local_scanner) or \
       (not os.path.isfile(settings.local_scanner))):
      raise Exception(f"Invalid local scanner path: {settings.local_scanner}")
  
  return settings
