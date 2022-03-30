#import numpy as np
#import pandas as pd
# financial data source
import yfinance as yf
# for logging and CLI arguments parsing
import configparser
from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

class Stock:
  def query_stocks(tickers, period='1d', interval='15m'):
    data = yf.download(tickers=tickers, period=period, interval=interval)
    print(data)

########################################
# CLI interface
########################################

def query_stocks(args):
  monitor = Stock.query_stocks(args.tickers)

def start_service(args):
  # use args.config as settings for the service
  # To-do
  i = 1

#################################
# Program starts
#################################
if __name__ == "__main__":
  CLI_config = { 'commands': [
    { 'name': 'query', 'help': 'Query latest quote for the tickers', 'func': query_stocks, 
      'params': [{ 'name': 'tickers', 'help': 'Ticker names', 'multi-value':'yes' }] },
    { 'name': 'config', 'help': 'Configure settings for running as service', 'func': start_service,
      'params': [{ 'name': 'filename', 'help': 'Config file for the settings' }] }
    ]}
  CLIParser.run(CLI_config)
