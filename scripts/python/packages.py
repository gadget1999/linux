import sys
import io
import os
from pathlib import Path
from datetime import datetime
import subprocess
import json
try:
  from importlib.metadata import distributions
except ImportError:
  from importlib_metadata import distributions  # For Python <3.8

def get_installation_date(package_name, package_path):
  """Try multiple methods to get installation date"""
  methods = [
    # Method 1: Use pip metadata if available
    lambda: get_date_from_pip_metadata(package_name),
    # Method 2: Use package directory creation time
    lambda: get_date_from_directory(package_path),
    # Method 3: Use most recent file modification time
    lambda: get_date_from_recent_file(package_path)
  ]
  
  for method in methods:
    try:
      date = method()
      if date:
        return date
    except:
      continue
  
  return 'Unknown'

def get_date_from_pip_metadata(package_name):
  """Try to get install date from pip metadata"""
  try:
    # This might work on some systems with newer pip versions
    result = subprocess.run(['pip', 'show', package_name], 
      capture_output=True, text=True)
    output = result.stdout
    # Look for any date-like information
    for line in output.split('\n'):
      if 'date' in line.lower() or 'time' in line.lower():
        return line.split(':', 1)[1].strip()
  except:
    pass
  return None

def get_date_from_directory(package_path):
  """Get date from directory creation time"""
  if package_path.exists():
    return datetime.fromtimestamp(package_path.stat().st_ctime).strftime('%Y-%m-%d')
  return None

def get_date_from_recent_file(package_path):
  """Get date from most recent file modification"""
  if package_path.exists():
    latest_mtime = 0
    for root, dirs, files in os.walk(package_path):
      for file in files:
        file_path = Path(root) / file
        latest_mtime = max(latest_mtime, file_path.stat().st_mtime)
    if latest_mtime > 0:
      return datetime.fromtimestamp(latest_mtime).strftime('%Y-%m-%d')
  return None

def get_package_sizes_with_dates():
  packages = []
  
  for dist in distributions():
    try:
      name = dist.metadata['Name'] if 'Name' in dist.metadata else dist.metadata.get('name', str(dist))
      version = dist.version
      location = Path(dist.locate_file(''))
      package_path = location / name.replace('-', '_')
      
      # Calculate size
      total_size = 0
      if package_path.exists():
        total_size = sum(f.stat().st_size for f in package_path.glob('**/*') if f.is_file())
      
      # Get installation date
      install_date = get_installation_date(name, package_path)
      
      packages.append({
        'name': name,
        'version': version,
        'size_mb': round(total_size / (1024 * 1024), 2),
        'install_date': install_date
      })
    except Exception as e:
      print(f"Error with {getattr(dist, 'metadata', dist)}: {e}")
      continue
  
  return sorted(packages, key=lambda x: x['size_mb'], reverse=True)

def main():
  sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
  packages = get_package_sizes_with_dates()
  print(f"{'Package':<25} {'Version':<12} {'Size (MB)':<10} {'Install Date':<12}")
  print("-" * 65)
  for pkg in packages[:15]:  # Show top 15
    try:
      print(f"{pkg['name']:<25} {pkg['version']:<12} {pkg['size_mb']:<10} {pkg['install_date']:<12}")
    except Exception as e:
      print(f"Error printing package info: {e}")
  # Show summary
  total_size = sum(pkg['size_mb'] for pkg in packages)
  print(f"\nTotal packages: {len(packages)}")
  print(f"Total size: {total_size:.2f} MB")

if __name__ == "__main__":
  main()
