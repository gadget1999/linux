import os
import re
import json
import hashlib
import requests
from datetime import datetime
import time
from pathlib import Path

# for logging and CLI arguments parsing
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

class ImmichUploader:
  def __init__(self, api_key, api_endpoint, folder_path):
    self.api_key = api_key
    self.api_endpoint = api_endpoint.rstrip('/')
    self.folder_path = folder_path
    self.upload_url = f"{self.api_endpoint}/api/assets"
    self.headers = {'Accept': 'application/json', 'x-api-key': self.api_key}
    self.config_file = os.path.expanduser("~") + "/.immich_sync_config"
    self.__get_reference_time()

  def __get_reference_time(self):
    try:
      key_hash = hashlib.md5(self.api_key.encode('utf-8')).hexdigest()
      with open(self.config_file, 'r', encoding='utf-8') as file:
        config_json = json.load(file)
      self.since_str = config_json[key_hash]
    except Exception:
      self.since_str = input("Enter reference time in format YYYYMMDD_HHMMSS: ")

  def save_reference_time(self):
    try:
      key_hash = hashlib.md5(self.api_key.encode('utf-8')).hexdigest()
      with open(self.config_file, 'w', encoding='utf-8') as file:
        data = {key_hash: self.since_str}
        json.dump(data, file, indent=4, ensure_ascii=False)
      logger.info(f"Reference time saved: {self.since_str}")
    except Exception as e:
      logger.error(f"Error saving reference time: {str(e)}")

  def get_changed_files(self):
    """Return files modified after the given timestamp"""
    changed_files = []
    
    for root, _, files in os.walk(self.folder_path):
      for file in files:
        file_path = Path(root) / file
        create_time = self.get_media_time(str(file_path))
        create_time_str = time.strftime("%Y%m%d_%H%M%S", create_time)
        if create_time_str > self.since_str:
          changed_files.append(str(file_path))
    
    return changed_files

  # Extracts the media creation time from the filename, returns a struct_time object
  def get_media_time(self, file_path):
    try:
      match = re.search(r"\D(\d{8}_\d{6})\D", file_path)  # Matches YYYYMMDD_HHMMSS
      if match:
        timestamp_str = match.group(1)
        return time.strptime(timestamp_str, "%Y%m%d_%H%M%S")
    except Exception as e:
      logger.error(f"Error getting media time for {file_path}: {str(e)}")
    stats = os.stat(file_path)
    if stats.st_mtime < 0:
      logger.debug(f"File {file_path} modification time is too old, using epoch time.")
      return time.localtime(0)
    else:
      return time.localtime(stats.st_mtime)

  def upload_file(self, file_path):
    """Upload a single file to Immich"""
    try:
      with open(file_path, 'rb') as f:
        file_name = os.path.basename(file_path)
        create_time = self.get_media_time(file_path)
        data = {
         'deviceAssetId': f'{file_name}-{time.strftime("%Y%m%d_%H%M%S", create_time)}',
         'deviceId': 'ImmichSync',
         'fileCreatedAt': datetime.fromtimestamp(time.mktime(create_time)).isoformat(),
         'fileModifiedAt': datetime.fromtimestamp(time.mktime(create_time)).isoformat(),
         'isFavorite': 'false'
        }
        files = {'assetData': f}
        response = requests.post(
          self.upload_url,
          headers=self.headers,
          data=data,
          files=files,
          verify=False  # Disable SSL verification for self-signed certificates
        )
      if response.status_code < 300:
        create_time_str = time.strftime("%Y%m%d_%H%M%S", create_time)
        logger.info(f"Uploaded: {file_path}")
        if create_time_str > self.since_str:
          self.since_str = create_time_str
        return True
      else:
        logger.error(f"Failed to upload {file_path}. Status code: {response.status_code}, Error: {response.text}")
        return False
    except Exception as e:
      logger.error(f"Error uploading {file_path}: {str(e)}")
      return False

  def upload_changed_files(self):
    """Find and upload all changed files"""
    changed_files = self.get_changed_files()
    if not changed_files:
      logger.info(f"No files changed since: {self.since_str}")
      return
    logger.info(f"Found {len(changed_files)} files to upload:")
    success_count = 0
    for file in changed_files:
      if self.upload_file(file):
        success_count += 1    
    if (success_count != len(changed_files)):
      logger.warn(f"Some files failed: {success_count}/{len(changed_files)} files uploaded.")
    self.save_reference_time()
  
def immich_sync(args):
  api_endpoint = os.environ['IMMICH_API_ENDPOINT']
  api_key = os.environ['IMMICH_API_KEY']
  uploader = ImmichUploader(
    api_key=api_key,
    api_endpoint=api_endpoint,
    folder_path=args.folder
  )
  uploader.upload_changed_files()

if __name__ == "__main__":
  CLI_config = { 'func':immich_sync, 'arguments': [
    {'name':'folder', 'help':'Folder path to monitor for changes'}
    ]}
  CLIParser.run(CLI_config)
