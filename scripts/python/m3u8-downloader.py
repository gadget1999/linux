import os, sys, time
import requests
import m3u8
from collections import namedtuple
from urllib.parse import urljoin
from pathvalidate import sanitize_filename
import subprocess

from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36'
WORK_DIR = os.environ['M3U8_WORK_DIR']
FFMPEG = "ffmpeg"
if "FFMPEG" in os.environ:
  FFMPEG = os.environ["FFMPEG"]
if not os.path.exists(FFMPEG):
  logger.error(f"FFmpeg not found: {FFMPEG}")
  exit(1)

# to get m3u8 playlist: use browser -> F12 -> Network -> Media
# m3u8 format:
# 1. m3u8: contains the playlists information, for adaptive streaming with different resolutions
# 2. envelope playlist: for one video with both video and audio playlists (this is a virtual playlist without .m3u8 file)
# 3. VOD playlist: the actual playlist with media segments, could be audio only, video only, or already mixed video and audio
#   (VOD means it's not live streaming, the #EXT-X-ENDLIST tag is set)

# playlist that contains the media segments
class M3U8_VOD_Playlist:
  def __init__(self, url):
    # basic properties
    self.Url = url
    self.__m3u8_obj = m3u8.load(url)
    self.Files = []
    for segment in self.__m3u8_obj.files:
      segment_url = urljoin(self.__m3u8_obj.base_uri, segment)
      Segment = namedtuple('Segment', ['name', 'uri'])
      self.Files.append(Segment(segment, segment_url))
    # download related properties
    self.Workarea = None
    self.TargetFile = None

  def Info(self):
    return f"URL: {self.Url}, Files: {len(self.Files)}"

  def __http_call(self, url):
    time.sleep(0.1)
    headers = { "User-Agent": USER_AGENT }
    response = requests.get(url, headers=headers)
    return response.content

  def __download_file(self, url, output):
    if os.path.exists(output):
      return
    data = self.__http_call(url)
    with open(output, "wb") as f:
      f.write(data)

  def __combine_segments(self, workarea, file_list, target_file):
    if not target_file or os.path.exists(target_file):
      logger.error(f"File already exists: {target_file}")
      return
    logger.debug(f"Combining segment files to {target_file}...")
    ffmpeg_cmd = f"{FFMPEG} -f concat -safe 0 -i \"{file_list}\" -c copy \"{target_file}\""
    status = subprocess.run(ffmpeg_cmd, cwd=workarea)
    return status

  def Download(self, workarea):
    self.Workarea = workarea
    # get final file name
    logger.info(f"Downloading playlist {self.Url} (total {len(self.Files)} segments) ...")
    ext = os.path.splitext(self.Files[0].name)[1]
    self.TargetFile = os.path.join(self.Workarea, f"CombinedSegments{ext}")
    # download segment files
    segment_list_file = os.path.join(self.Workarea, "Segments.txt")
    segment_list = []
    for index, segment in enumerate(self.Files):
      segment_file_path = os.path.join(self.Workarea, segment.name)
      self.__download_file(segment.uri, segment_file_path)
      segment_list.append(f"file '{segment_file_path}'\n")
      if (index + 1) % 10 == 0:
        print(f"{index + 1}", end='', flush=True)
      else:
        print('.', end='', flush=True)
    logger.debug(f"Saving segment list file [self.List_file]...")
    with open(segment_list_file, "w") as f:
      f.writelines(segment_list)
    # combine segments to one file
    self.__combine_segments(self.Workarea, segment_list_file, self.TargetFile)

class M3U8_Envelope_Playlist:
  def __init__(self, m3u8_playlist):
    # basic properties
    self.Resolution = min(m3u8_playlist.stream_info.resolution)
    self.VideoUri = m3u8_playlist.absolute_uri
    self.AudioUri = None
    for media in m3u8_playlist.media:
      if (media.type == "AUDIO") and (media.group_id == m3u8_playlist.stream_info.audio):
        self.AudioUri = media.absolute_uri
        break
    # download related properties
    self.Workarea = None
    self.VideoPlaylist = None
    self.AudioPlaylist = None

  def Info(self):
    return f"Video: {self.VideoUri}, Resolution: {self.Resolution}p, Audio: {self.AudioUri}"
 
  def Download(self, workarea):
    self.Workarea = workarea
    # download video and audio files
    self.VideoPlaylist = M3U8_VOD_Playlist(self.VideoUri)
    self.VideoPlaylist.Download(workarea)
    if self.AudioUri:
      # need to mix video and audio files, use subfolder for audio segments
      audio_workarea = os.path.join(workarea, "audio")
      logger.debug(f"Creating working folder for audio [{audio_workarea}]...")
      os.makedirs(audio_workarea, exist_ok=True)
      self.AudioPlaylist = M3U8_VOD_Playlist(self.AudioUri)
      self.AudioPlaylist.Download(audio_workarea)

class M3U8:
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
      for playlist in self.__m3u8_obj.playlists:
        self.Playlists.append(M3U8_Envelope_Playlist(playlist))
    elif self.__m3u8_obj.playlist_type.lower() == "vod":
      self.Playlists.append(M3U8_VOD_Playlist(self.Url))
    else:
      logger.error(f"Playlist type is not supported: {self.m3u8_obj.playlist_type}")

  # combine streams to MP4
  def __combine_video_audio(self, target_file, video_file, audio_file = None):
    if not audio_file:
      logger.info(f"Creating final file: {target_file}...")
      ffmpeg_cmd = f"{FFMPEG} -i \"{video_file}\" -c copy -bsf:a aac_adtstoasc \"{target_file}\""
    else:
      # combine video and audio files
      logger.info(f"Combining video and audio files to {target_file}...")
      ffmpeg_cmd = f"{FFMPEG} -i \"{video_file}\" -i \"{audio_file}\" -c copy -bsf:a aac_adtstoasc \"{target_file}\""

    status = subprocess.run(ffmpeg_cmd, cwd=self.Workarea)
    return status
  
  # if there are multiple playlists, use preference to select (default: max resolution)
  # preference: '+': max resolution, '-': min resolution, '+|-number': match resolution if possible
  def __select_playlist(self, preference):
    if (self.Playlists.count == 1):
      return self.Playlists[0]
    # sort the playlists by resolution
    self.Playlists.sort(key=lambda x: x.Resolution)
    # try to match the resolution
    if len(preference) > 1:
      preferred_resolution = int(preference[1:])
      for playlist in self.Playlists:
        if playlist.Resolution == preferred_resolution:
          return playlist
    # if no match, return the min or max resolution    
    if preference[0] == '+':
      return self.Playlists[-1]
    elif preference[0] == '-':
      return self.Playlists[0]
    else:
      logger.error(f"Invalid preference: {preference}")
      return None

  def Download(self, title, root_folder, preference="+"):
    self.Title = title
    self.Workarea = os.path.join(root_folder, title)
    logger.debug(f"Creating working folder [{self.Workarea}]...")
    os.makedirs(self.Workarea, exist_ok=True)
    # download media file(s) according to preference
    playlist = self.__select_playlist(preference)
    playlist.Download(self.Workarea)
    # create final video
    self.TargetFile = os.path.join(root_folder, f"{title}.mp4")
    if playlist.AudioPlaylist:
      # need to mix video and audio files
      logger.debug(f"Combining video and audio files to {self.TargetFile}...")
      self.__combine_video_audio(self.TargetFile, playlist.VideoPlaylist.TargetFile,
                                 playlist.AudioPlaylist.TargetFile)
    else:
      logger.debug(f"Creating final file: {self.TargetFile}...")
      self.__combine_video_audio(self.TargetFile, playlist.VideoPlaylist.TargetFile)

#################################
# Program starts
#################################

if __name__ == "__main__":
  args = sys.argv
  url = None
  title = None
  if len(args) == 3:
    # usage: m3u8-downloader.py [url title]
    url = args[1]
    title = sanitize_filename(args[2])
  else:
    url = input("Enter the m3u8 URL: ")
    title = sanitize_filename(input("Enter the title: "))
  downloader = M3U8(url)
  downloader.Download(title, WORK_DIR, "+720")
