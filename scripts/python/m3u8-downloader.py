import os, sys, time
import requests
from urllib.parse import urljoin
import subprocess

from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/112.0'
WORK_DIR = os.environ['M3U8_WORK_DIR']
FFMPEG = "ffmpeg"
if "FFMPEG" in os.environ:
  FFMPEG = os.environ["FFMPEG"]

class M3U8:
  def __http_call(self, url):
    time.sleep(1)
    headers = { "User-Agent": USER_AGENT }
    response = requests.get(url, headers=headers)
    return response.content

  def __download_file(self, url, output):
    if os.path.exists(output):
      return
    data = self.__http_call(url)
    with open(output, "wb") as f:
      f.write(data)

  def __init__(self, url, root_folder):
    self.Url = url
    self.Name = os.path.basename(url)
    self.Workarea = os.path.join(root_folder, self.Name)
    self.List_file = os.path.join(self.Workarea, "Segments.txt")
    self.Combined_file = ""
    logger.info(f"Creating working folder [{self.Workarea}]...(URL={url})")
    os.makedirs(self.Workarea, exist_ok=True)

  def Download(self):
    logger.info(f"Downloading m3u8 ...")
    playlist_text = self.__http_call(self.Url).decode("utf-8")
    # process the playlist text to extract the URLs of the media segments
    media_segments = [line.strip() for line in playlist_text.split("\n") if line.strip() and not line.startswith("#")]
    segment_list = []
    # download the media segments
    base_url = urljoin(self.Url, ".")
    for segment in media_segments:
      segment_url = urljoin(base_url, segment)
      segment_file_name = os.path.join(self.Workarea, segment)
      if not self.Combined_file:
        ext = os.path.splitext(segment_file_name)[1]
        self.Combined_file = os.path.join(self.Workarea, f"CombinedSegments{ext}")
      self.__download_file(segment_url, segment_file_name)
      segment_list.append(f"file '{segment_file_name}'\n")
      print('.', end='')
    logger.info(f"Saving segment list (total {len(segment_list)} entries) ...")
    with open(self.List_file, "w") as f:
      f.writelines(segment_list)

  def CombineSegments(self):    
    if not self.Combined_file or os.path.exists(self.Combined_file):
      return

    logger.info(f"Combining segment files to {self.Combined_file}...")
    ffmpeg_cmd = f"{FFMPEG} -f concat -safe 0 -i \"{self.List_file}\" -c copy \"{self.Combined_file}\""
    status = subprocess.run(ffmpeg_cmd, cwd=self.Workarea)
    return status

class M3U8Downloader:
  def DownloadStreams(urls, title):
    root_folder = os.path.join(WORK_DIR, title)
    logger.info(f"Creating root folder [{root_folder}]...)")
    os.makedirs(root_folder, exist_ok=True)

    combined_list = []
    for url in urls:
      worker = M3U8(url, root_folder)
      worker.Download()
      worker.CombineSegments()
      combined_list.append(worker.Combined_file)

    # combine streams to MP4
    output_file = os.path.join(root_folder, f"{title}.mp4")
    logger.info(f"Combining video and audio files to {output_file}...")
    # build the FFmpeg command
    ffmpeg_cmd = [f"{FFMPEG}"]
    for input_file in combined_list:
      ffmpeg_cmd.extend(["-i", f"{input_file}"])
    ffmpeg_cmd.extend([
      "-c", "copy",
      "-bsf:a", "aac_adtstoasc",
      f"{output_file}"])
    subprocess.run(ffmpeg_cmd)

#################################
# Program starts
#################################

if __name__ == "__main__":
  args = sys.argv
  if len(args) < 2: exit()
  urls = []  
  title = None
  index = 1
  while (index < len(args)):
    arg = args[index]; index += 1
    if arg.lower().startswith("https://"):
      urls.append(arg)
    else:
      title = arg
  M3U8Downloader.DownloadStreams(urls, title)
