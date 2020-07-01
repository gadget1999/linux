#!/usr/bin/env python3

import os, sys
import codecs
import json
import time, datetime
# for struct-like class
import copy
from dataclasses import dataclass
# for web APIs
import socket
import requests
from urllib.parse import urlparse
# for unittest
import unittest
# for logging and CLI arguments parsing
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

class GitHubSearch:
  # raw api layer
  def __api_call(url, headers, params=None):
    api_key = os.environ['GITHUB_API_KEY'].strip('\" ')
    headers['Authorization'] = f"token {api_key}"
    r = requests.get(url, headers=headers, params=params)
    if r.status_code == 403:
      # retry after one minute
      logger.warning(f"Throttled, sleeping for some time.")
      time.sleep(60)
      r = requests.get(url, headers=headers, params=params)
    # if failed or failed after retry, bail out
    if r.status_code > 400:
      raise Exception(f"GitHub API failed: error={r.status_code}")
    # result is fine
    quota_left = r.headers._store['x-ratelimit-remaining'][1]
    if quota_left == 1:
      logger.warning(f"No rate quota left. Sleeping for some time.")
      time.sleep(60)
    return r

  # search code hits, load pages if needed
  def __search_code(keyword, exclude_owner=None):
    url = 'https://api.github.com/search/code'
    headers = {'Accept':'application/vnd.github.v3+json'}
    query = keyword
    if exclude_owner:
      query += f"+-org:{exclude_owner}"
    params = {'q':query, 'sort':'indexed', 'order':'desc'}
    logger.debug(f"Fetching results for: {query}")
    r = GitHubSearch.__api_call(url, headers, params)
    items = r.json()['items']
    while 'next' in r.links:
      # need to fetch more pages until complete
      next_link = r.links['next']['url']
      # slow down to avoid hitting throttling
      time.sleep(5)
      logger.debug(f"Fetching paged results: {next_link}")
      r = GitHubSearch.__api_call(next_link, headers, params)
      items += r.json()['items']
    return items

  def search_code(keyword, history, exclude_owner=None):
    items = GitHubSearch.__search_code(keyword, exclude_owner)
    results = {}
    for item in items:
      try:
        path = item['path']
        url = item['html_url']
        owner_name = item['repository']['owner']['login']
        if exclude_owner and owner_name == exclude_owner:
          continue
        repo_name = item['repository']['name']
        full_path = f"{owner_name}/{repo_name}/{path}"
        if full_path in history:
          #logger.debug(f"Old entry: {full_path}")
          continue
        logger.info(f"New entry: {full_path}")
        history.add(full_path)
        if owner_name not in results:
          results[owner_name] = {}
        owner = results[owner_name]
        if repo_name not in owner:
          owner[repo_name] = []
        repo = owner[repo_name]
        repo.append({'path':path, 'url':url})
      except Exception as e:
        logger.error(f"Parsing {url} failed: {e}")
    return results

@dataclass
class EmailConfig:
  api_key: str
  sender: str
  recipients: str

class GitHubMonitor:
  __html_GitHub_report_template = """
<html>
 <head>
  <title>GitHub Report</title>
 </head>
 <body>
  {% for owner in results %}
   <p>
    <b>Owner: {{ owner }}</b><br>
    {% for repo in results[owner] %}
     <b>Repo: {{ repo }}</b><br>
     {% for item in results[owner][repo] %}
      <a href="{{ item.url }}">{{ item.path }}</a><br>
     {% endfor %}
    {% endfor %}
   </p>
  {% endfor %}
 </body>
</html>
"""

  def generate_html_report(results, output_file=None):
    from jinja2 import Template

    engine = Template(GitHubMonitor.__html_GitHub_report_template)
    html = engine.render(results=results)
    if output_file:
      with codecs.open(output_file, 'w', "utf-8") as f:
        f.write(html)
    return html

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

  def send_email_report(results):
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (Mail, MimeType, Attachment, FileContent, FileName,
      FileType, Disposition, ContentId)
    import base64

    email_config = GitHubMonitor.__load_email_config()
    if not email_config or not results:
      return
    try:
      # construct email
      email = Mail()
      email.from_email = email_config.sender
      for recipient in email_config.recipients:
        email.add_to(recipient)
      today = time.strftime('%Y-%m-%d', time.localtime())
      email.subject = f"[{today}] GitHub Monitoring Report"
      email.add_content(GitHubMonitor.generate_html_report(results), MimeType.html)
      # send email
      sendgrid = SendGridAPIClient(email_config.api_key)
      r = sendgrid.send(email)
      if r.status_code > 400:
        logger.error(f"SendGrid API failed: error={r.status_code}")
    except Exception as e:
      logger.error(f"Failed to send Site SSL Report: {e}")

  ##############################
  # Instance level functiosn
  ##############################
  def __init__(self, history_file):
    self.__history_file = history_file
    self.__load_history()

  def __load_history(self):
    self.__history = set()
    if not os.path.exists(self.__history_file):
      logger.debug(f"No history records found.")
      return
    with open(self.__history_file) as f:
      history = json.load(f)
    for item in history:
      self.__history.add(item)
    logger.info(f"History loaded: {len(self.__history)} records.")

  def __save_history(self):
    item_list = []
    for item in self.__history:
      item_list.append(item)
    if len(item_list) == 0:
      return
    logger.info(f"Saving history: {len(item_list)} records.")
    with codecs.open(self.__history_file, 'w', "utf-8") as f:
      json.dump(sorted(item_list), f, indent=1)

  def monitor_keyword(self, keyword, exclude_owner):
    results = GitHubSearch.search_code(keyword, self.__history, exclude_owner)
    if len(results) == 0:
      logger.info("No new entries found.")
      return
    # save new entries and send email
    self.__save_history()
    GitHubMonitor.send_email_report(results)

class GitHubTestCase(unittest.TestCase):
  def test_search_github(self):
    monitor = GitHubMonitor('/tmp/history.txt')
    monitor.monitor_keyword('gitgraber', 'hisxo')
    #GitHubMonitor.generate_html_report(results, '/tmp/000.html')

if 'UNIT_TEST' in os.environ:
  test = GitHubTestCase()
  test.test_search_github()

########################################
# CLI interface
########################################

def monitor_github(args):
  keyword = args.keyword
  work_folder = args.work_folder
  exclude_owner = args.exclude_owner
  if not keyword or not work_folder:
    raise Exception("Invalid arguments: keyword and work_folder are must-have.")
  app_name = CLIParser.get_app_name()
  history_file = f"{work_folder}/{app_name}-{keyword}.txt"
  monitor = GitHubMonitor(history_file)
  monitor.monitor_keyword(keyword, exclude_owner)

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
  CLI_config = { 'func':monitor_github, 'arguments': [
    {'name':'--keyword', 'help':'Keyword being monitored'}, 
    {'name':'--work_folder', 'help':'Working area to store data'}, 
    {'name':'--exclude_owner', 'help':'Owner to exclude from search'}
    ]}
  try:
   parser = CLIParser.get_parser(CLI_config)
   CLIParser.run(parser)
  except Exception as e:
   logger.error(f"Exception happened: {e}")
   sys.exit(1)
