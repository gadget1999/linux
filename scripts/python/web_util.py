#!/usr/bin/env python3

import time
import socket
import ipaddress
import urllib.parse
import requests
import dns.resolver
import common

# Initialize logger
logger = common.Logger.getLogger()

class WebUtils:
  """Utility class for web-related functions like DNS resolution, IP location, etc."""
  
  # Class-level constant for user agent
  _USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"

  @staticmethod
  def get_latest_user_agent():
    """Update the user agent string to the latest version"""
    try:
      url = "https://jnrbsn.github.io/user-agents/user-agents.json"
      r = requests.get(url)
      if r.status_code >= 400:
        logger.warning(f"Failed to get latest user agent list. (status={r.status_code})")
        return
      user_agent = r.json()[0]
      if user_agent.startswith("Mozilla/") and user_agent != WebUtils._USER_AGENT:
        logger.debug(f"Found a newer user agent: {user_agent}")
        WebUtils._USER_AGENT = user_agent
    except Exception as e:
      logger.warning(f"Failed to get the latest user agent list. ({e})")

  @staticmethod
  def is_host_reachable(url):
    """Check if a host is reachable using custom DNS and socket connection"""
    try:
      parsed_uri = urllib.parse.urlparse(url)
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

  @staticmethod
  def get_ip_addresses(host, port):
    """Get all IP addresses for a given host and port"""
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

  @staticmethod
  def get_ip_location(ip):
    """Get geographic location information for an IP address"""
    try:
      url = f"https://ipinfo.io/{ip}/json"
      time.sleep(2)   # avoid throttling
      headers = {
        "User-Agent": WebUtils._USER_AGENT
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

  @staticmethod
  def get_url_location(url):
    """Get geographic location information for a URL"""
    try:
      parsed_uri = urllib.parse.urlparse(url)
      ip = socket.gethostbyname(parsed_uri.hostname)
      return WebUtils.get_ip_location(ip)
    except Exception as e:
      logger.warning(f"Failed to get location of url: {url} ({e})")
      return None, None, None

  @staticmethod
  def is_ipv6(ip):
    """Check if an IP address is IPv6"""
    try:
      ipaddress.IPv6Address(ip)
      return True
    except:
      return False

  @staticmethod
  def is_valid_dns(fqdn):
    """Check if a FQDN can be resolved via DNS"""
    try:
      socket.gethostbyname(fqdn)
      return True, None
    except Exception as e:
      return False, f"Failed to resolve {fqdn}: {e}"

  @staticmethod
  def get_user_agent():
    """Get the current user agent string"""
    return WebUtils._USER_AGENT

  @staticmethod
  def set_user_agent(new_user_agent):
    """Set a new user agent string"""
    WebUtils._USER_AGENT = new_user_agent

# Provide module-level functions for backward compatibility
def get_latest_user_agent():
  return WebUtils.get_latest_user_agent()

def is_host_reachable(url):
  return WebUtils.is_host_reachable(url)

def get_ip_addresses(host, port):
  return WebUtils.get_ip_addresses(host, port)

def get_ip_location(ip):
  return WebUtils.get_ip_location(ip)

def get_url_location(url):
  return WebUtils.get_url_location(url)

def is_ipv6(ip):
  return WebUtils.is_ipv6(ip)

def is_valid_dns(fqdn):
  return WebUtils.is_valid_dns(fqdn)

def get_user_agent():
  return WebUtils.get_user_agent()

def set_user_agent(new_user_agent):
  return WebUtils.set_user_agent(new_user_agent)
