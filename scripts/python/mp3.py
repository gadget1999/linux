#!/usr/bin/env python3

''' Utility class to manage MP3 files in batch
'''
import os
from pydub import AudioSegment
# logging
from common import Logger, ExitSignal, CLIParser
logger = Logger.getLogger()

class MP3File:
  def __init__(self, path):
    self.name = os.path.basename(path)
    self.__audio_stream = AudioSegment.from_mp3(path)
    self.length = self.__audio_stream.duration_seconds
    self.channels = self.__audio_stream.channels
    self.max_vol = self.__audio_stream.max_dBFS
    self.avg_vol = self.__audio_stream.dBFS

  def vol_up(self, gain = None):
    if not gain:
      gain = -self.max_vol
    self.__audio_stream += gain

  def save(self, path):
    self.__audio_stream.export(path, format='mp3')

class MP3_Utility:
  def enum_mp3_files(path, func):
    if os.path.isfile(path):
      func(path)
    elif os.path.isdir(path):
      for root, directories, files in os.walk(path):
        for name in files:
          if name.endswith('.mp3'):
            MP3_Utility.enum_mp3_files(os.path.join(root, name), func)

  def show_mp3_info(path):
    mp3 = MP3File(path)
    logger.debug(f"{mp3.name} (len={mp3.length}s, {mp3.channels} channels)")
    logger.debug(f"> Max={mp3.max_vol:.1f}dB, Avg={mp3.avg_vol:.1f}dB")

  def add_mp3_vol(path):
    mp3 = MP3File(path)
    mp3.vol_up()
    mp3.save(path + ".mp3")

########################################
# CLI interface
########################################

def list_mp3(args):
  for path in args.paths:
    MP3_Utility.enum_mp3_files(path, MP3_Utility.show_mp3_info)

def gain_mp3(args):
  for path in args.paths:
    MP3_Utility.enum_mp3_files(path, MP3_Utility.add_mp3_vol)

#################################
# Program starts
#################################

if (__name__ == '__main__'):
  ExitSignal.register()

  CLI_config = { 'commands': [
    { 'name': 'list', 'help': 'List MP3 files with info', 'func': list_mp3, 
      'params': [{ 'name': 'paths', 'help': 'MP3 file or folder', 'multi-value':'yes' }] },
    { 'name': 'gain', 'help': 'Increase MP3 volume without cropping', 'func': gain_mp3, 
      'params': [{ 'name': 'paths', 'help': 'MP3 file or folder', 'multi-value':'yes' }] }
    ]}
  try:
    parser = CLIParser.get_parser(CLI_config)
    CLIParser.run(parser)
  except Exception as e:
    logger.error(f"Exception happened: {e}")
