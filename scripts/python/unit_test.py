#!/usr/bin/env python3

import os
import sys
import unittest

# Import the modules we want to test
# Ensure the current directory is in the Python path so we can import web-monitor modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the classes and functions we want to test
# Since the main file is web-monitor.py, we need to import it using importlib
import importlib.util
spec = importlib.util.spec_from_file_location("web_monitor", "web-monitor.py")
web_monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web_monitor)

# Also import web utilities
import web_util

# Now we can access the classes
SiteInfo = web_monitor.SiteInfo
WebMonitor = web_monitor.WebMonitor

class SiteInfoTestCase(unittest.TestCase):
  def test_get_site_report(self):
    report = SiteInfo.get_report("http://us.cloud-learning.net:37828/forecast", True)
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SiteInfo.get_report("https://www.google.com", False)
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SiteInfo.get_report("https://www.google.com", True)
    self.assertEqual(len(report), 2, 'wrong number of records')
    report = SiteInfo.get_report("https://www.google1.com", True)
    self.assertEqual(len(report), 1, 'wrong number of records')
    report = SiteInfo.get_report("https://www.indiaglitz.com", False)
    self.assertEqual(len(report), 1, 'wrong number of records')

class WebMonitorTestCase(unittest.TestCase):
  def test_webmonitor_report(self):
    urls = ['https://www.google.com', 'https://www.google1.com']
    monitor = WebMonitor('src/web-monitor.cfg')  # Assuming a test config exists
    report, has_down = monitor._get_report(urls, True)
    self.assertEqual(len(report), 2, 'wrong number of records')
    
    # Test report generation
    monitor._generate_xlsx_report(report, '/tmp/000.xlsx')
    
    # Test email functionality if configured
    if monitor._email_settings:
      # Note: Actual email sending would require valid SendGrid API key
      pass

if __name__ == '__main__':
  # Run all tests when this file is executed directly
  unittest.main()

# Legacy support for environment variable-based testing
if 'UNIT_TEST' in os.environ:
  # Run individual test cases as before
  site_test = SiteInfoTestCase()
  #site_test.test_get_site_report()
  
  monitor_test = WebMonitorTestCase()
  monitor_test.test_webmonitor_report()
