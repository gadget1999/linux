#!/usr/bin/env python3

''' Utility class to manage MP3 files in batch
'''
import os
from pydub import AudioSegment
import eyed3
# logging
from common import Logger, ExitSignal, CLIParser
logger = Logger.getLogger()
# disable debug from libraries
import logging
logging.getLogger("pydub").setLevel(logging.WARNING)
logging.getLogger("eyed3").setLevel(logging.WARNING)
logging.getLogger("ffmpeg").setLevel(logging.WARNING)

class MP3File:
  def __init__(self, path):
    self.name = os.path.basename(path)
    self.__audio_stream = AudioSegment.from_mp3(path)
    self.length = self.__audio_stream.duration_seconds
    self.channels = self.__audio_stream.channels
    self.max_vol = self.__audio_stream.max_dBFS
    self.avg_vol = self.__audio_stream.dBFS
    audiofile = eyed3.load(path)
    self.bitrate = audiofile.info.bit_rate[1]
    self.artist = audiofile.tag.artist
    self.album = audiofile.tag.album
    self.title = audiofile.tag.title

  def vol_up(self, gain = None):
    if not gain:
      gain = -self.max_vol
    if gain > 1:
      self.__audio_stream += gain
    return gain

  def save(self, path):
    tags = {}
    tags['artist'] = self.artist
    tags['album'] = self.album
    tags['title'] = self.title
    bitrate = f"{self.bitrate}K"
    self.__audio_stream.export(path, format='mp3', bitrate=bitrate, tags=tags)

class MP3_Utility:
  def enum_mp3_files(path, func, *args):
    if os.path.isfile(path):
      func(path, args)
    elif os.path.isdir(path):
      for root, directories, files in os.walk(path):
        for name in files:
          if name.endswith('.mp3'):
            MP3_Utility.enum_mp3_files(os.path.join(root, name), func, args)

  def show_mp3_info(path):
    mp3 = MP3File(path)
    logger.debug(f"{mp3.name} (len={mp3.length}s, {mp3.channels} channels, bitrate={mp3.bitrate}K)")
    logger.debug(f"> Max={mp3.max_vol:.1f}dB, Avg={mp3.avg_vol:.1f}dB")
    logger.debug(f"> {mp3.album} - {mp3.title}")

  def add_mp3_vol(path, overwrite = False):
    mp3 = MP3File(path)
    gain = mp3.vol_up()
    if gain > 1:
      if overwrite:
        new_file = path
      else:
        base_file = os.path.splitext(path)[0]
        new_file = base_file + "_vol.mp3"
      logger.info(f"Saving [{mp3.name}] to: {new_file} (gain={gain:.1f}dB)")
      mp3.save(new_file)
    else:
      logger.debug(f"Skipping [{mp3.name}] (gain={gain:.1f}dB)")

########################################
# CLI interface
########################################

def list_mp3(args):
  for path in args.paths:
    MP3_Utility.enum_mp3_files(path, MP3_Utility.show_mp3_info)

def gain_mp3(args):
  for path in args.paths:
    MP3_Utility.enum_mp3_files(path, MP3_Utility.add_mp3_vol, True)

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
