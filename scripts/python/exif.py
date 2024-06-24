#!/usr/bin/env python3

''' Utility class to manage JPG files EXIF in batch
'''
import os
from datetime import datetime, timedelta
import re
import zlib
from PIL import Image, ExifTags
# logging
from common import Logger, ExitSignal, CLIParser
logger = Logger.getLogger()
# disable debug from libraries
import logging
logging.getLogger("PIL").setLevel(logging.WARNING)

class GuessDate:
  # assuming file is in a folder structure like Year/Month/[day] structure
  # if day not specified, use 1st
  # assuming time is random between 3-6PM
  def from_path(path):
    folder_path = os.path.dirname(path)
    date_pattern = r"\b(19\d{2}|20\d{2})[\/\\](0[1-9]|1[0-2])[\/\\]?(0[1-9]|[12]\d|3[01])?\b$"
    date_matched = re.findall(date_pattern, folder_path)
    if not date_matched:
      raise Exception(f"Folder structure is invalid: {path}")
    dates = date_matched[0]
    year = dates[0]
    month = dates[1]
    day = dates[2] if (len(dates) == 3 and dates[2]) else "01"
    date_base = datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d")
    hash_value = zlib.crc32(path.encode())
    seconds_to_add = 54000 + hash_value % 10800  # between 15:00-18:00
    return date_base + timedelta(seconds=seconds_to_add)

class EXIF:
  TAG_CAMERA = 272
  TAG_TIME_TAKEN = 306

  def __init__(self, path):
    self.__jpg_stream = None
    self.__path = path
    self.Name = os.path.basename(path)
    self.Camera = ""
    self.TimeTaken = ""

  def load_exif(self):      
    self.__jpg_stream = Image.open(self.__path)
    self.__exif_info = self.__jpg_stream.getexif()
    if self.__exif_info:
      self.Camera = self.__exif_info.get(EXIF.TAG_CAMERA)     
      self.TimeTaken = self.__exif_info.get(EXIF.TAG_TIME_TAKEN)

  def save_exif(self):
    if (self.Camera == self.__exif_info.get(EXIF.TAG_CAMERA) and
      self.TimeTaken == self.__exif_info.get(EXIF.TAG_TIME_TAKEN)):
      return
    self.__exif_info[EXIF.TAG_TIME_TAKEN] = self.TimeTaken
    self.__exif_info[EXIF.TAG_CAMERA] = self.Camera
    logger.info(f"{self.__path}: set new date to {self.TimeTaken}")
    self.__jpg_stream.save(self.__path, exif=self.__exif_info)

  def close(self):
    if self.__jpg_stream:
      self.__jpg_stream.close()

class EXIF_Utility:
  def enum_jpg_files(path, func, *args):
    if os.path.isfile(path):
      func(path, args)
    elif os.path.isdir(path):
      for root, directories, files in os.walk(path):
        for name in files:
          if name.lower().endswith('.jpg'):
            EXIF_Utility.enum_jpg_files(os.path.join(root, name), func, args)

  def show_jpg_info(path, *args):
    jpg = EXIF(path)
    try:
      jpg.load_exif()
      logger.debug(f"{jpg.Name}: {jpg.Camera} on {jpg.TimeTaken}")
    except Exception as e:
      logger.error(f"Failed to get EXIF of [{path}]: {e}")
    finally:
      jpg.close()

  def tag_one_jpg(path, *args):
    jpg = EXIF(path)
    try:
      jpg.load_exif()
      logger.debug(f"{jpg.Name}: {jpg.Camera} on {jpg.TimeTaken}")
      timestamp = GuessDate.from_path(path)
      jpg.TimeTaken = timestamp.strftime("%Y-%m-%d %H:%M:%S")
      jpg.save_exif()      
    except Exception as e:
      logger.error(f"Failed to tag EXIF for [{path}]: {e}")
    finally:
      jpg.close()

########################################
# CLI interface
########################################

def list_jpg(args):
  for path in args.paths:
    EXIF_Utility.enum_jpg_files(path, EXIF_Utility.show_jpg_info)

def tag_jpg(args):
  for path in args.paths:
    EXIF_Utility.enum_jpg_files(path, EXIF_Utility.tag_one_jpg)

#################################
# Program starts
#################################

if (__name__ == '__main__'):
  ExitSignal.register()

  CLI_config = { 'commands': [
    { 'name': 'list', 'help': 'List JPG files with info', 'func': list_jpg, 
      'params': [{ 'name': 'paths', 'help': 'JPG file or folder', 'multi-value':'yes' }] },
    { 'name': 'tag', 'help': 'Tag JPG files date according to folder structure', 'func': tag_jpg, 
      'params': [{ 'name': 'paths', 'help': 'JPG file or folder', 'multi-value':'yes' }] }
    ]}
  try:
    CLIParser.run(CLI_config)
  except Exception as e:
    logger.error(f"Exception happened: {e}")
