import argparse
import logging, logging.handlers
import os
import re
import time
import json
import requests

class AzureSubscription:
  def __init__(self, subscription_id, subscription_name):
    self.Name = subscription_name
    self.Id = subscription_id

VM_STATUS_STOPPED = "stopped"
VM_STATUS_DEALLOCATED = "deallocated"
VM_STATUS_DEALLOCATING = "deallocating"
VM_STATUS_RUNNING = "running"
VM_STATUS_STARTING = "starting"
class AzureVM:
  def __init__(self, cli, vm_json):
    self._azure_cli = cli
    vm_id = vm_json["id"]
    # parse resource group from id: e.g., /subscriptions/<GUID>/resourceGroups/
    self.subscription_id = re.search('\/subscriptions\/(.+?)\/resourceGroups\/', vm_id).group(1)
    # parse resource group from id: e.g., /resourceGroups/<NAME>/providers/
    self.resource_group_name = re.search('\/resourceGroups\/(.+?)\/providers\/', vm_id).group(1)
    self.name = vm_json["name"]
    size = vm_json['properties']['hardwareProfile']['vmSize']
    self.size = re.search('Standard_(.*)', size).group(1)
    self.os = vm_json['properties']['storageProfile']['osDisk']['osType']
    self.location = vm_json["location"]

  def GetStatus(self):
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Compute/virtualMachines/{self.name}/instanceView?api-version=2019-07-01"
    response = self._azure_cli.API_call(API_URL)
    return response['statuses'][-1]['code'].split('/')[-1]

  def Start(self):
    status = self.GetStatus()
    if (status in {VM_STATUS_RUNNING, VM_STATUS_STARTING}):
      logger.debug(f"Skipping... (VM status: {status})")
      return

    logger.info(f"Starting VM [{self.name}]...")
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Compute/virtualMachines/{self.name}/start?api-version=2019-07-01"
    self._azure_cli.API_call_post(API_URL)

    # check if operation completed
    for _ in range(30):
      if (self.GetStatus() == VM_STATUS_RUNNING):
        logger.info("Completed.")
        break
      time.sleep(10)
    else:
      logger.error("Operation timed out")

  def Stop(self):
    status = self.GetStatus()
    if (status in {VM_STATUS_DEALLOCATED, VM_STATUS_DEALLOCATING}):
      logger.debug(f"Skipping... (VM status: {status})")
      return

    logger.info(f"Stopping VM [{self.name}]...")
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Compute/virtualMachines/{self.name}/deallocate?api-version=2019-07-01"
    self._azure_cli.API_call_post(API_URL)

    # check if operation completed
    for _ in range(30):
      if (self.GetStatus() == VM_STATUS_DEALLOCATED):
        logger.info("Completed.")
        break
      time.sleep(10)
    else:
      logger.error("Operation timed out")

  def Restart(self):
    self.Stop()
    self.Start()

  def ShowSummary(self):
    print(f"""  VM: {vm.name}
   Subscription: {vm.subscription_id}
   Resource Group: {vm.resource_group_name}
   Size: {vm.size}
   OS: {vm.os}
      """)

AZURE_LOGIN_ENDPOINT = "https://login.microsoftonline.com"
AZURE_API_ENDPOINT = "https://management.azure.com"
class AzureCLI:
  _access_token = None
  _subscriptions = []
  _virtual_machines = []

  ########################################
  # Private methods
  ########################################

  def __init__(self, tenant_id, app_id, app_key):
    self.TenantId = tenant_id
    self.__login(tenant_id, app_id, app_key)

  def __login(self, tenant_id, app_id, app_key):
    API_URL = f"{AZURE_LOGIN_ENDPOINT}/{tenant_id}/oauth2/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": app_id,
        "client_secret": app_key,
        "resource": AZURE_API_ENDPOINT
      }
    response = self.API_call(API_URL, data=params)
    self._access_token = response['access_token']

  def __load_subscriptions(self):
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions?api-version=2019-11-01"
    response = self.API_call(API_URL)
    for subscription in response["value"]:
      subscription_id = subscription["subscriptionId"]
      subscription_name = subscription["displayName"]
      self._subscriptions.append(AzureSubscription(subscription_id, subscription_name))

  def __load_virtual_machines(self, subscription_id):
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{subscription_id}/providers/Microsoft.Compute/virtualMachines?api-version=2019-07-01"
    response = self.API_call(API_URL)
    for vm in response["value"]:
      self._virtual_machines.append(AzureVM(self, vm))

  ########################################
  # Public methods
  ########################################

  @property
  def subscriptions(self):
    if not self._subscriptions:
      self.__load_subscriptions()
    return self._subscriptions

  @property
  def virtual_machines(self):
    if not self._virtual_machines:
      for subscription in self.subscriptions:
        self.__load_virtual_machines(subscription.Id)
    return self._virtual_machines

  def find_virtual_machine(self, vm_name):
    for vm in self.virtual_machines:
      if (vm.name.lower() == vm_name.lower()):
        return vm
    return None

  def API_call(self, url, data=None, headers=None):
    if (self._access_token is not None):
      headers = { "Authorization": f"Bearer {self._access_token}" }
    response = requests.get(url, data=data, headers=headers, timeout=60)
    assert (response is not None), "API result is empty."
    assert (response.status_code < 400), "API returned error: {response.status_code}"
    content_type = response.headers['Content-Type']
    assert ('application/json' in content_type), "API result is not in JSON formatreturned error: {content_type}"
    return response.json()

  def API_call_post(self, url, data=None, headers=None):
    if (self._access_token is not None):
      headers = { "Authorization": f"Bearer {self._access_token}" }
    response = requests.post(url, data=data, headers=headers, timeout=60)
    assert (response is not None), "API result is empty."
    assert (response.status_code < 400), "API returned error: {response.status_code}"
  
########################################
# CLI interface
########################################

def restart(args):
  logger.debug(f"CMD - Restarting virtual machines: {args.names}")
  for vm_name in args.names:
    target_vm = vm_cli.find_virtual_machine(vm_name)
    if (target_vm is not None):
      target_vm.Restart()
    else:
      logger.error(f"VM was not found: {vm_name}")

def start(args):
  logger.debug(f"CMD - Starting virtual machines: {args.names}")
  for vm_name in args.names:
    target_vm = vm_cli.find_virtual_machine(vm_name)
    if (target_vm is not None):
      target_vm.Start()
    else:
      logger.error(f"VM was not found: {vm_name}")

def stop(args):
  logger.debug(f"CMD - Stopping virtual machines: {args.names}")
  for vm_name in args.names:
    target_vm = vm_cli.find_virtual_machine(vm_name)
    if (target_vm is not None):
      target_vm.Stop()
    else:
      logger.error(f"VM was not found: {vm_name}")

def list_vms(args):
  logger.debug("Listing all virtual machines...")
  for vm in vm_cli.virtual_machines:
    status = vm.GetStatus()
    print(f"{vm.name:14}{vm.os:10}{vm.location:15}{vm.size:9}{status}")

def stop_idle(args):
  logger.debug("Shutdown idle Windows virtual machines...")
  for vm in vm_cli.virtual_machines:
    if vm.os == "Windows":
      status = vm.GetStatus()
      if (status == VM_STATUS_STOPPED):
        vm.Stop()

def get_parser():
  parser = argparse.ArgumentParser('azvm')
  subparsers = parser.add_subparsers(title='commands')

  list_parser = subparsers.add_parser('list', help='List virtual machines')
  list_parser.set_defaults(func=list_vms)

  stop_idle_parser = subparsers.add_parser('stop-idle', help='Shutdown idle virtual machines')
  stop_idle_parser.set_defaults(func=stop_idle)

  start_parser = subparsers.add_parser('start', help='Start virtual machines')
  start_parser.add_argument('names', nargs='+', help='Virtual machines names')
  start_parser.set_defaults(func=start)

  stop_parser = subparsers.add_parser('stop', help='Stop virtual machines')
  stop_parser.add_argument('names', nargs='+', help='Virtual machines names')
  stop_parser.set_defaults(func=stop)

  restart_parser = subparsers.add_parser('restart', help='Restart virtual machines')
  restart_parser.add_argument('names', nargs='+', help='Virtual machines names')
  restart_parser.set_defaults(func=restart)
  return parser

#################################
# Program starts
#################################

LOGFILE = "/tmp/azure-vm.log"
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

init_logger()
TENANT = os.environ['AZURE_TENANT_ID']
APP_ID = os.environ['AZURE_APP_ID']
APP_KEY = os.environ['AZURE_APP_KEY']
vm_cli = AzureCLI(TENANT, APP_ID, APP_KEY)

if __name__ == "__main__":
  parser = get_parser()
  args = parser.parse_args()
  args.func(args)