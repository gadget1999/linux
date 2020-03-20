import argparse
import logging, logging.handlers
import os, sys
import win32api
import _winapi
import shutil

RAM_DRIVE = "R:"
LOGFILE = f"{RAM_DRIVE}/Logs/ram-disk.log"
logger = logging.getLogger("")
def init_logger():
  logger.setLevel(logging.INFO)
  if "DEBUG" in os.environ:
    logger.setLevel(logging.DEBUG)
  formatter = logging.Formatter("%(asctime)s: %(levelname)s - %(message)s")

  fileHandler = logging.handlers.RotatingFileHandler(LOGFILE)
  fileHandler.setFormatter(formatter)
  fileHandler.setLevel(logging.INFO)
  logger.addHandler(fileHandler)

  consoleHandler = logging.StreamHandler()
  consoleHandler.setFormatter(formatter)
  consoleHandler.setLevel(logging.DEBUG)
  logger.addHandler(consoleHandler)

def get_parser():
  parser = argparse.ArgumentParser('ramdisk')
  subparsers = parser.add_subparsers(title='commands')

  migrate_parser = subparsers.add_parser('migrate', help='Migrate a folder to RAM disk')
  migrate_parser.add_argument('source', help='Source folder path')
  migrate_parser.add_argument('target', help='Target folder path')
  migrate_parser.set_defaults(func=migrate)
  return parser

def migrate_folder(source, target):
  try:
    create_link = False
    if not os.path.isdir(source):
      logger.error(f"[{source}] does not exist or is not a directory.")
      return

    source_backup=f"{source}.sav"
    # seems Python does not support dictory junction well (os.path.islink is always False)
    # use isdir AND !exists to guess dictory junction condition
    if os.path.exists(source):
      # not a junction, rename source first before copying
      logger.info(f"Renaming {source} to {source_backup}...")
      os.rename(source, source_backup)
      create_link = True

    # copy folder content only if target not created yet
    if not os.path.exists(target):
      logger.info(f"Copying content from {source_backup} to {target}...")
      shutil.copytree(source_backup, target, copy_function = shutil.copy)

    if create_link:
      logger.info(f"Creating link from {source} to {source_backup}...")
      #win32api.CreateSymbolicLink(source, target)
      _winapi.CreateJunction(target, source)

  except Exception:
    logger.error("Failed to migrate from {source} to {target}.", exc_info=True)

def migrate(args):
  logger.debug(f"CMD - Migrate folder {args.source} to {args.target}")
  migrate_folder(args.source, args.target)

init_logger()

if __name__ == "__main__":
  parser = get_parser()
  args = parser.parse_args()
  if len(sys.argv) > 1:
    args.func(args)
