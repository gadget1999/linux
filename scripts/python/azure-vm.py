import argparse
import os, sys
import re
import time
import json
import requests

from common import Logger, CLIParser
logger = Logger.getLogger()
Logger.disable_http_tracing()

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
  __access_token = None
  __subscriptions = []
  __virtual_machines = []

  ########################################
  # Private methods
  ########################################

  def __init__(self, tenant_id, app_id, app_key):
    self.TenantId = tenant_id
    self.__login(tenant_id, app_id, app_key)

  def __request_with_retry(self, func, url, data, headers, timeout):
    for i in range(3): # retry up to 3 times
      try:
        response = func(url=url, data=data, headers=headers, timeout=timeout)
        if (response.status_code < 400): return response
        logger.error(f"API returned: {response.status_code} (retries={i})")
      except Exception as e:
        logger.error(f"Failed to connect to API endpoint: {e} (retries={i})")
      time.sleep(30)
    return None

  def __login(self, tenant_id, app_id, app_key):
    API_URL = f"{AZURE_LOGIN_ENDPOINT}/{tenant_id}/oauth2/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": app_id,
        "client_secret": app_key,
        "resource": AZURE_API_ENDPOINT
      }
    response = self.API_call(API_URL, data=params)
    self.__access_token = response['access_token']

  def __load_subscriptions(self):
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions?api-version=2019-11-01"
    response = self.API_call(API_URL)
    for subscription in response["value"]:
      subscription_id = subscription["subscriptionId"]
      subscription_name = subscription["displayName"]
      self.__subscriptions.append(AzureSubscription(subscription_id, subscription_name))

  def __load_virtual_machines(self, subscription_id):
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{subscription_id}/providers/Microsoft.Compute/virtualMachines?api-version=2019-07-01"
    response = self.API_call(API_URL)
    for vm in response["value"]:
      self.__virtual_machines.append(AzureVM(self, vm))

  ########################################
  # Public methods
  ########################################

  def API_call(self, url, data=None, headers=None):
    if (self.__access_token is not None):
      headers = { "Authorization": f"Bearer {self.__access_token}" }
    response = self.__request_with_retry(requests.get, url, data, headers, 60)
    assert (response is not None), "API result is empty."
    assert (response.status_code < 400), f"API returned error: {response.status_code}"
    content_type = response.headers['Content-Type']
    assert ('application/json' in content_type), f"API result is not in JSON formatreturned error: {content_type}"
    return response.json()

  def API_call_post(self, url, data=None, headers=None):
    if (self.__access_token is not None):
      headers = { "Authorization": f"Bearer {self.__access_token}" }
    response = self.__request_with_retry(requests.post, url, data, headers, 60)
    assert (response is not None), "API result is empty."
    assert (response.status_code < 400), f"API returned error: {response.status_code}"

  def API_call_put(self, url, data=None, headers=None):
    if (self.__access_token is not None):
      headers = { "Authorization": f"Bearer {self.__access_token}",
               "Content-Type": "application/json" }
    response = self.__request_with_retry(requests.put, url, data, headers, 60)
    assert (response is not None), "API result is empty."
    assert (response.status_code < 400), f"API returned error: {response.status_code}"

  @property
  def subscriptions(self):
    if not self.__subscriptions:
      self.__load_subscriptions()
    return self.__subscriptions

  @property
  def virtual_machines(self):
    if not self.__virtual_machines:
      for subscription in self.subscriptions:
        self.__load_virtual_machines(subscription.Id)
    return self.__virtual_machines

  def find_virtual_machine(self, vm_name):
    for vm in self.virtual_machines:
      if (vm.name.lower() == vm_name.lower()):
        return vm
    return None

  def add_ip_whitelist(self, rule_id, ip_list):
    API_URL = f"{AZURE_API_ENDPOINT}/{rule_id}?api-version=2020-04-01"
    logger.info(f"Getting current NSG rule settings...")
    response = self.API_call(API_URL)
    rule = response['properties']
    old_list = rule['sourceAddressPrefixes']
    need_update = False
    for ip in ip_list:
      if ip not in old_list:
        need_update = True
    if need_update:
      rule['sourceAddressPrefixes'] = ip_list
      logger.info(f"Updating NSG rule settings with IPs: {ip_list}")
      response = self.API_call_put(API_URL, data=str(response))
      logger.info(f"Completed.")
    else:
      logger.info(f"No need to update NSG rule settings.")
  
########################################
# CLI interface
########################################

def restart_vms(args):
  #logger.debug(f"CMD - Restarting virtual machines: {args.names}")
  for vm_name in args.names:
    target_vm = vm_cli.find_virtual_machine(vm_name)
    if (target_vm is not None):
      target_vm.Restart()
    else:
      logger.error(f"VM was not found: {vm_name}")

def start_vms(args):
  #logger.debug(f"CMD - Starting virtual machines: {args.names}")
  for vm_name in args.names:
    target_vm = vm_cli.find_virtual_machine(vm_name)
    if (target_vm is not None):
      target_vm.Start()
    else:
      logger.error(f"VM was not found: {vm_name}")

def stop_vms(args):
  #logger.debug(f"CMD - Stopping virtual machines: {args.names}")
  for vm_name in args.names:
    target_vm = vm_cli.find_virtual_machine(vm_name)
    if (target_vm is not None):
      target_vm.Stop()
    else:
      logger.error(f"VM was not found: {vm_name}")

def list_vms(args):
  #logger.debug("Listing all virtual machines...")
  for vm in vm_cli.virtual_machines:
    status = vm.GetStatus()
    if not args.charged_only or status != VM_STATUS_DEALLOCATED:
      print(f"{vm.name:14}{vm.os:10}{vm.location:15}{vm.size:9}{status}")

def stop_idle_vms(args):
  #logger.debug("Shutdown idle virtual machines...")
  for vm in vm_cli.virtual_machines:
    status = vm.GetStatus()
    if (status == VM_STATUS_STOPPED):
      vm.Stop()

def add_ip_whitelist(args):
  rule_id = args.rule_id
  ip_list = args.ip
  vm_cli.add_ip_whitelist(rule_id, ip_list)

#################################
# Program starts
#################################

TENANT = os.environ['AZURE_TENANT_ID']
APP_ID = os.environ['AZURE_APP_ID']
APP_KEY = os.environ['AZURE_APP_KEY']
vm_cli = AzureCLI(TENANT, APP_ID, APP_KEY)

if __name__ == "__main__":
  CLI_config = { 'commands': [
    { 'name': 'list', 'help': 'List virtual machines', 'func': list_vms, 
      'params': [{ 'name': '--charged-only', 'action': 'store_true', 'help': 'Only list ones not in deallocated status' }] },
    { 'name': 'stop-idle', 'help': 'Shutdown idle virtual machines', 'func': stop_idle_vms },
    { 'name': 'add-ip', 'help': 'Add current public IP to NSG rule whitelist', 'func': add_ip_whitelist, 
      'params': [{ 'name': 'rule_id', 'help': 'NSG rule id' },
                 { 'name': 'ip', 'help': 'IP ranges', 'multi-value':'yes' }] },
    { 'name': 'start', 'help': 'Start virtual machines', 'func': start_vms, 
      'params': [{ 'name': 'names', 'help': 'Virtual machines names', 'multi-value':'yes' }] },
    { 'name': 'stop', 'help': 'Stop virtual machines', 'func': stop_vms,
      'params': [{ 'name': 'names', 'help': 'Virtual machines names', 'multi-value':'yes' }] },
    { 'name': 'restart', 'help': 'Restart virtual machines', 'func': restart_vms,
      'params': [{ 'name': 'names', 'help': 'Virtual machines names', 'multi-value':'yes' }] }
    ]}
  try:
   parser = CLIParser.get_parser(CLI_config)
   CLIParser.run(parser)
  except Exception as e:
   logger.error(f"Exception happened: {e}")
   sys.exit(1)