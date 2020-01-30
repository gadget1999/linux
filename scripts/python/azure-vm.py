import argparse
import os
import re
import time
import json
import requests

class AzureSubscription:
  def __init__(self, subscription_id, subscription_name):
    self.Name = subscription_name
    self.Id = subscription_id

VM_STATUS_DEALLOCATED = "PowerState/deallocated"
VM_STATUS_DEALLOCATING = "PowerState/deallocating"
VM_STATUS_RUNNING = "PowerState/running"
VM_STATUS_STARTING = "PowerState/starting"
class AzureVM:
  def __init__(self, cli, vm_json):
    self._azure_cli = cli
    vm_id = vm_json["id"]
    # parse resource group from id: e.g., /subscriptions/<GUID>/resourceGroups/
    self.subscription_id = re.search('\/subscriptions\/(.+?)\/resourceGroups\/', vm_id).group(1)
    # parse resource group from id: e.g., /resourceGroups/<NAME>/providers/
    self.resource_group_name = re.search('\/resourceGroups\/(.+?)\/providers\/', vm_id).group(1)
    self.name = vm_json["name"]
    self.size = vm_json['properties']['hardwareProfile']['vmSize']
    self.os = vm_json['properties']['storageProfile']['osDisk']['osType']

  def GetStatus(self):
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Compute/virtualMachines/{self.name}/instanceView?api-version=2019-07-01"
    response = self._azure_cli.API_call(API_URL)
    return response['statuses'][-1]['code']

  def Start(self):
    status = self.GetStatus()
    if (status in {VM_STATUS_RUNNING, VM_STATUS_STARTING}):
      print(f"Skipping... (VM status: {status})")
      return

    print(f"Starting VM [{self.name}]...")
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Compute/virtualMachines/{self.name}/start?api-version=2019-07-01"
    self._azure_cli.API_call_post(API_URL)

    # check if operation completed
    for _ in range(30):
      if (self.GetStatus() == VM_STATUS_RUNNING):
        print("Completed.")
        break
      time.sleep(10)
    else:
      print("Operation timed out")

  def Stop(self):
    status = self.GetStatus()
    if (status in {VM_STATUS_DEALLOCATED, VM_STATUS_DEALLOCATING}):
      print(f"Skipping... (VM status: {status})")
      return

    print(f"Stopping VM [{self.name}]...")
    API_URL = f"{AZURE_API_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/{self.resource_group_name}/providers/Microsoft.Compute/virtualMachines/{self.name}/deallocate?api-version=2019-07-01"
    self._azure_cli.API_call_post(API_URL)

    # check if operation completed
    for _ in range(30):
      if (self.GetStatus() == VM_STATUS_DEALLOCATED):
        print("Completed.")
        break
      time.sleep(10)
    else:
      print("Operation timed out")

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

def restart(vm_name):
  target_vm = next(filter(lambda x: x.name == vm_name, vm_cli.virtual_machines))
  if (target_vm is not None):
    target_vm.Restart()

def get_parser():
  parser = argparse.ArgumentParser('Azure VM CLI')
  parser.add_argument('--restart', '-r', type=restart,
                        help='Restart a VM')
  return parser

TENANT = os.environ['AZURE_TENANT_ID']
APP_ID = os.environ['AZURE_APP_ID']
APP_KEY = os.environ['AZURE_APP_KEY']
vm_cli = AzureCLI(TENANT, APP_ID, APP_KEY)

if __name__ == "__main__":
  parser = get_parser()
  args = parser.parse_args(args)
