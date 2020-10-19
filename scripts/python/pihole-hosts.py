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
# for logging and CLI arguments parsing
import configparser
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

class PiholeHostsParser:
  #########################################
  # Internal helper functions
  #########################################

  def __process_remote_file(self, url):
    entries = set()
    try:
      r = requests.get(url, stream=True)
      r.encoding = 'utf-8'
      for line in r.iter_lines(decode_unicode=True):
        if line: entries.add(line.strip())
      logger.info(f"Processed [{url}]: {len(entries)} entries found.")
    except Exception as e:
      logger.error(f"Failed to download [{url}]: {e}")
    finally:
      return entries

  def __generate_hosts_file(self, hosts, hosts_file):
    logger.info(f"Generating hosts file to [{hosts_file}] ({len(hosts)} entries)")
    with open(hosts_file, 'w', encoding="utf-8") as f:
      for host in hosts:
        f.write(f"0.0.0.0\t{host}\n")

  #########################################
  # Public methods
  #########################################

  def get_config_list(self, config, section, option):
    value = config.get(section, option)
    return list(filter(None, (x.strip() for x in value.splitlines())))

  def __init__(self, configfile):
    try:
      config = configparser.ConfigParser()
      config.read(configfile)
      self.__blocklists = self.get_config_list(config, "Blocklist", "URLs")
      self.__output = config.get("Output", "FilePath")
      if "Ignorelist" in config:
        self.__ignorelists = self.get_config_list(config, "Ignorelist", "URLs")
      else:
        self.__ignorelists = set()
    except Exception as e:
      logger.error(f"Config file {configfile} is invalid: {e}")
      raise

  def build_hosts_file(self):
    full_list = set()
    # add blocklist from files
    for url in self.__blocklists:
      full_list |= self.__process_remote_file(url)
    # remove entries in ignore files
    for url in self.__ignorelists:
      full_list -= self.__process_remote_file(url)
    # build final list according to entries in memory
    self.__generate_hosts_file(full_list, self.__output)

########################################
# CLI interface
########################################

def build_hosts_file(args):
  builder = PiholeHostsParser(args.config)
  builder.build_hosts_file()

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
  CLI_config = { 'func':build_hosts_file, 'arguments': [
    {'name':'config', 'help':'Config file for pi-hole host compiling'} 
    ]}
  try:
   parser = CLIParser.get_parser(CLI_config)
   CLIParser.run(parser)
  except Exception as e:
   logger.error(f"Exception happened: {e}")
   sys.exit(1)
