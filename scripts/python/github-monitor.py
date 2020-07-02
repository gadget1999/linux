#!/usr/bin/env python3

import os, sys
import codecs
import json
import time, datetime
import re
# for struct-like class
import copy
from dataclasses import dataclass
# for web APIs
import socket
import requests
import urllib.parse
# for unittest
import unittest
# for logging and CLI arguments parsing
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

@dataclass
class GitHubItem:
  owner: str
  repo: str
  path: str
  url: str

class GitHubSearch:
  # raw api layer
  def __api_call(url, headers, params=None):
    api_key = os.environ['GITHUB_API_KEY'].strip('\" ')
    headers['Authorization'] = f"token {api_key}"
    logger.debug(f"Invoking GitHub API: {url}")
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
  def __paged_api_call(url, headers, params=None):
    r = GitHubSearch.__api_call(url, headers)
    r_json = r.json()
    logger.debug(f"Found {r_json['total_count']} hits.")
    items = r_json['items']
    while 'next' in r.links:
      # need to fetch more pages until complete
      next_link = r.links['next']['url']
      # slow down to avoid hitting throttling
      time.sleep(5)
      r = GitHubSearch.__api_call(next_link, headers)
      items += r.json()['items']
    return items

  # search code hits, load pages if needed
  def search_code(keyword, exclude_owner=None, language=None):
    headers = {'Accept':'application/vnd.github.v3+json'}
    query = urllib.parse.quote(keyword)
    if language:      
      query += f"+language:{urllib.parse.quote(language)}"
    if exclude_owner:
      query += f"+-org:{urllib.parse.quote(exclude_owner)}"
    # build URL directly to avoid requests URL encoding q field, which GitHub does not support
    url = f"https://api.github.com/search/code?q={query}&sort=indexed&order=desc"
    items = GitHubSearch.__paged_api_call(url, headers)
    records = []
    for item in items:
      owner_name = item['repository']['owner']['login']
      repo_name = item['repository']['name']
      path = item['path']
      url = item['html_url']
      records.append(GitHubItem(owner_name, repo_name, path, url))
    return records

  def search_issues(keyword, exclude_owner=None):
    headers = {'Accept':'application/vnd.github.v3+json'}
    query = urllib.parse.quote(keyword)
    if exclude_owner:
      query += f"+-org:{urllib.parse.quote(exclude_owner)}"
    # build URL directly to avoid requests URL encoding q field, which GitHub does not support
    url = f"https://api.github.com/search/issues?q={query}&sort=updated&order=desc"
    items = GitHubSearch.__paged_api_call(url, headers)
    records = []
    for item in items:
      url = item['html_url']
      # assuming the url format is https://github.com/{owner}/{repo}/issues/{number}
      pattern = '(?<!/)/([^/]+)/([^/]+)/(.+)'
      matches = re.search(pattern, url)
      owner_name = matches.group(1)
      repo_name = matches.group(2)
      path = matches.group(3)
      records.append(GitHubItem(owner_name, repo_name, path, url))
    return records

@dataclass
class EmailConfig:
  api_key: str
  sender: str
  recipients: str

class GitHubMonitor:
  __html_GitHub_report_template = """
<html>
 <head>
  <title>GitHub Monitoring Report</title>
 </head>
 <body>
  <h1>GitHub Monitoring Report</h1>
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

  def __get_tree_from_records(records):
    tree = {}
    for item in records:
      if item.owner not in tree:
        tree[item.owner] = {}
      owner = tree[item.owner]
      if item.repo not in owner:
        owner[item.repo] = []
      repo = owner[item.repo]
      repo.append({'path':item.path, 'url':item.url})
    return tree

  def generate_html_report(new_items, output_file=None):
    from jinja2 import Template

    engine = Template(GitHubMonitor.__html_GitHub_report_template)
    tree = GitHubMonitor.__get_tree_from_records(new_items)
    html = engine.render(results=tree)
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

  def send_email_report(new_items):
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import (Mail, MimeType, Attachment, FileContent, FileName,
      FileType, Disposition, ContentId)
    import base64

    email_config = GitHubMonitor.__load_email_config()
    if not email_config or not new_items:
      return
    try:
      # construct email
      email = Mail()
      email.from_email = email_config.sender
      for recipient in email_config.recipients:
        email.add_to(recipient)
      today = time.strftime('%Y-%m-%d', time.localtime())
      email.subject = f"[{today}] GitHub Monitoring Report"
      email.add_content(GitHubMonitor.generate_html_report(new_items), MimeType.html)
      # send email
      sendgrid = SendGridAPIClient(email_config.api_key)
      logger.info(f"Sending email report...")
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
    items = GitHubSearch.search_code(keyword, exclude_owner, "JavaScript")
    items += GitHubSearch.search_code(keyword, exclude_owner, "C#")
    items += GitHubSearch.search_issues(keyword, exclude_owner)
    new_items = []
    for item in items:
      full_path = f"{item.owner}/{item.repo}/{item.path}"
      if full_path in self.__history:
        #logger.debug(f"Old entry: {full_path}")
        continue
      logger.info(f"New entry: {full_path}")
      self.__history.add(full_path)
      new_items.append(item)
    if len(new_items) == 0:
      logger.info("No new entries found.")
      return
    # save new entries and send email
    self.__save_history()
    GitHubMonitor.send_email_report(new_items)

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
