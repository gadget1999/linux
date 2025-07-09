import os, sys, time
import requests
import m3u8
import subprocess

from dataclasses import dataclass
from pathvalidate import sanitize_filename

from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

DEBUG = False
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
WORK_DIR = os.environ['M3U8_WORK_DIR']
FFMPEG = "ffmpeg"
if "DEBUG" in os.environ:  DEBUG = True
if "FFMPEG" in os.environ: FFMPEG = os.environ["FFMPEG"]
if not os.path.exists(FFMPEG):
  logger.error(f"FFmpeg not found: {FFMPEG}")
  exit(1)

# to get m3u8 playlist: use browser -> F12 -> Network -> Media
# m3u8 format:
# 1. envelope: contains the playlists information, for adaptive streaming with different resolutions
# 2. playlist: for one video with both video and audio streams seaparted or mixed (this is a virtual playlist without .m3u8 file)
# 3. stream: the actual media stream with segments, could be audio only, video only, or both already mixed
#   (VOD means it's not live streaming, the #EXT-X-ENDLIST tag is set)

# playlist that contains the media segments
@dataclass
class M3U8_Media_Segment:
  uri: str = ''
  name: str = ''
  duration: float = 0.0

class M3U8_VOD_Stream:
  def __init__(self, url):
    # basic properties
    self.Url = url
    self.__ignore_ssl_errors = True if "DEBUG" in os.environ else False
    self.__m3u8_obj = m3u8.load(url)
    self.Duration = 0.0
    self.Segments = []
    for segment in self.__m3u8_obj.segments:
      tmp_segment = M3U8_Media_Segment(name=segment.uri, uri=segment.absolute_uri, duration=segment.duration)
      self.Duration += tmp_segment.duration
      self.Segments.append(tmp_segment)
    # download related properties
    self.Workarea = None
    self.TargetFile = None

  def Info(self):
    return f"URL: {self.Url} ({int(self.Duration)}s, {len(self.Segments)} segments)"

  def __http_call(self, url):
    if not DEBUG: time.sleep(1)
    headers = { "User-Agent": USER_AGENT }
    response = requests.get(url, headers=headers, verify=self.__ignore_ssl_errors)
    return response.content

  def __download_file(self, url, output):
    if os.path.exists(output): return
    data = self.__http_call(url)
    with open(output, "wb") as f:
      f.write(data)

  def __combine_segments(self, workarea, file_list, target_file):
    if not target_file or os.path.exists(target_file):
      logger.error(f"File already exists: {target_file}")
      return
    logger.debug(f"Combining segment files to {target_file}...")
    ffmpeg_cmd = [FFMPEG, '-f', 'concat', '-safe', '0',
                  '-i', file_list,
                  '-c', 'copy',
                  target_file]
    try:
      result = subprocess.run(
        ffmpeg_cmd,
        cwd=workarea,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
        )
      logger.debug(f"Completed successfully: {os.path.getsize(target_file):,} bytes")
      return True, result.stdout
    except subprocess.CalledProcessError as e:
      logger.error(f"Failed to combine segments: {e.stderr}")
      return False, e.stderr

  def Download(self, workarea):
    self.Workarea = workarea
    # get final file name
    logger.debug(f"Downloading playlist {self.Info()} ...")
    self.TargetFile = os.path.join(self.Workarea, f"CombinedSegments.mp4")
    # download segment files
    segment_list_file = os.path.join(self.Workarea, "Segments.txt")
    segment_list = []
    for index, segment in enumerate(self.Segments):
      segment_file_path = os.path.join(self.Workarea, sanitize_filename(segment.name))
      self.__download_file(segment.uri, segment_file_path)
      segment_list.append(f"file '{segment_file_path}'\n")
      if (index + 1) % 10 == 0:
        print(f"{index + 1}", end='', flush=True)
      else:
        print('.', end='', flush=True)
    print('')
    #logger.debug(f"Saving segment list file [self.List_file]...")
    with open(segment_list_file, "w") as f:
      f.writelines(segment_list)
    # combine segments to one file
    self.__combine_segments(self.Workarea, segment_list_file, self.TargetFile)

class M3U8_Playlist:
  def __init__(self, m3u8_playlist = None):
    # download related properties
    self.HasVideo = True
    self.Resolution = 0
    self.Name = None
    self.VideoUri = None
    self.AudioUri = None
    self.Workarea = None
    self.VideoStream = None
    self.AudioStream = None
    # basic properties
    self.HasVideo = True
    if (not m3u8_playlist) or (not m3u8_playlist.stream_info.resolution):
      self.HasVideo = False
      return
    self.Resolution = min(m3u8_playlist.stream_info.resolution)
    self.Name = m3u8_playlist.uri
    self.VideoUri = m3u8_playlist.absolute_uri
    self.AudioUri = None
    for media in m3u8_playlist.media:
      if (media.type == "AUDIO") and (media.group_id == m3u8_playlist.stream_info.audio):
        self.AudioUri = media.absolute_uri
        break

  def Info(self):
    return f"Video: {self.Name}, Resolution: {self.Resolution}p, Audio: {not not self.AudioUri}"

  def Download(self, workarea):
    self.Workarea = workarea
    # download video and audio files
    self.VideoStream = M3U8_VOD_Stream(self.VideoUri)
    self.VideoStream.Download(workarea)
    if self.AudioUri:
      # need to mix video and audio files, use subfolder for audio segments
      audio_workarea = os.path.join(workarea, "audio")
      logger.debug(f"Creating working folder for audio [{audio_workarea}]...")
      os.makedirs(audio_workarea, exist_ok=True)
      self.AudioStream = M3U8_VOD_Stream(self.AudioUri)
      self.AudioStream.Download(audio_workarea)

class M3U8_Envelope:
  def __init__(self, url):
    # basic properties
    self.Url = url
    self.__m3u8_obj = m3u8.load(url)
    self.Playlists = []
    self.__load_playlists()
    # download related properties
    self.Title = None
    self.Workarea = None
    self.TargetFile = None

  def __load_playlists(self):
    if not self.__m3u8_obj.playlist_type:
      # this is not the playlist with media segments
      for index, playlist in enumerate(self.__m3u8_obj.playlists):
        tmp_playlist = M3U8_Playlist(playlist)
        if tmp_playlist.HasVideo:
          logger.debug(f"Playlist {index + 1}: {tmp_playlist.Info()}")
          self.Playlists.append(tmp_playlist)
    elif self.__m3u8_obj.playlist_type.lower() == "vod":
      tmp_playlist = M3U8_Playlist()
      tmp_playlist.Url = self.Url
      tmp_playlist.Name = "VOD_Stream"
      tmp_playlist.VideoUri = self.Url
      tmp_playlist.VideoStream = M3U8_VOD_Stream(self.Url)
      self.Playlists.append(tmp_playlist)
    else:
      logger.error(f"Playlist type is not supported: {self.m3u8_obj.playlist_type}")

  # if there are multiple playlists, use preference to select (default: max resolution)
  # preference: '+': max resolution, '-': min resolution, 'number+|-': match resolution 'num' if possible
  def __select_playlist(self, preference):
    if (len(self.Playlists) == 1): return self.Playlists[0]
    # sort the playlists by resolution
    self.Playlists.sort(key=lambda x: x.Resolution)
    # try to match the resolution
    if not preference: preference = "+"
    if len(preference) > 1:
      preferred_resolution = int(preference[:-1])
      for playlist in self.Playlists:
        if playlist.Resolution == preferred_resolution:
          return playlist
    # if no match, return the min or max resolution    
    if preference[-1] == '+':   return self.Playlists[-1]
    elif preference[-1] == '-': return self.Playlists[0]
    else:
      logger.error(f"Invalid preference: {preference}")
      return None

  # combine streams to MP4
  def __combine_video_audio(self, target_file, video_file, audio_file = None):
    ffmpeg_cmd = [FFMPEG, "-i", video_file]
    if audio_file:
      # combine video and audio files
      logger.debug(f"Combining video and audio files to {target_file}...")      
      ffmpeg_cmd.extend(['-i', audio_file])
    #ffmpeg_cmd.extend(['-c', 'copy', '-bsf:a', 'aac_adtstoasc', target_file])
    ffmpeg_cmd.extend(['-c', 'copy', target_file])
    try:
      result = subprocess.run(
        ffmpeg_cmd,
        cwd=self.Workarea,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
        )
      logger.info(f"Completed successfully: {os.path.getsize(target_file):,} bytes")
      return True, result.stdout
    except subprocess.CalledProcessError as e:
      logger.error(f"Failed to create final video: {e.stderr}")
      return False, e.stderr
    
  def __delete_folder(self, path):
    for item in os.listdir(path):
      item_path = os.path.join(path, item)
      if os.path.isfile(item_path):
        os.remove(item_path)
      else:
        self.__delete_folder(item_path)  # Recursive call for subdirectories
    os.rmdir(path)

  def Download(self, title, root_folder, preference="+"):
    self.TargetFile = os.path.join(root_folder, f"{title}.mp4")
    if os.path.exists(self.TargetFile):
      logger.error(f"File already exists: {self.TargetFile}")
      return
    if not self.Playlists:
      logger.error(f"No playlist found for {self.Url}")
      return
    self.Title = title
    self.Workarea = os.path.join(root_folder, title)
    logger.info(f"Processing [{title}] (pref: {preference}, Uri: {self.Url})...")
    os.makedirs(self.Workarea, exist_ok=True)
    # download media file(s) according to preference
    if len(self.Playlists) == 1:
      playlist = self.Playlists[0]
    else:
      playlist = self.__select_playlist(preference)
      logger.debug(f"Selected playlist: {playlist.Info()}")
    playlist.Download(self.Workarea)
    # create final video
    video_file = playlist.VideoStream.TargetFile
    audio_file = None
    if playlist.AudioStream:
      audio_file = playlist.AudioStream.TargetFile
    self.__combine_video_audio(self.TargetFile, video_file, audio_file)
    # cleanup if not in debug mode
    if not DEBUG:
      logger.debug(f"Cleaning up working folder [{self.Workarea}]...")
      self.__delete_folder(self.Workarea)

#################################
# Program starts
#################################

if __name__ == "__main__":
  args = sys.argv
  url = None
  title = None
  preference = None
  if len(args) in [3, 4]:
    # usage: m3u8-downloader.py [url title]
    url = args[1]
    title = sanitize_filename(args[2])
    if len(args) == 4: preference = args[3]
  else:
    DEBUG = True
    url = input("Enter the m3u8 URL: ")
    title = sanitize_filename(input("Enter the title: "))
    preference = input("Enter the resolution preference ([num]+/-, default: +): ")
  downloader = M3U8_Envelope(url)
  downloader.Download(title, WORK_DIR, preference)
