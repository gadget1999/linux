import os
import re

from azure.common.credentials import ServicePrincipalCredentials
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.subscription import SubscriptionClient
from msrestazure.azure_exceptions import CloudError

class AzureVM:
  def __init__(self, subscription_id, rg_name, vm_name):
    self.SubscriptionId = subscription_id
    self.ResourceGroupName = rg_name
    self.Name = vm_name

class AzureCLI:
  _computeClients = dict()
  VMs = dict()

  # Private methods

  def __init__(self, tenant_id, app_id, app_key):
    self.TenantId = tenant_id
    self._credentials = ServicePrincipalCredentials(client_id = app_id,
                                       secret = app_key,
                                       tenant = tenant_id)
    self.__load_all_vms()

  def __get_subscriptions(self):
    subscription_client = SubscriptionClient(self._credentials)
    return subscription_client.subscriptions.list()

  def __load_all_vms(self):
    subs = self.__get_subscriptions()
    for sub in subs:
      subscription_id = sub.subscription_id
      self._computeClients[subscription_id] = ComputeManagementClient(self._credentials, subscription_id)
      self.__load_vms(subscription_id)

  def __load_vms(self, subscription_id):
    if subscription_id not in self._computeClients:
      self._computeClients[subscription_id] = ComputeManagementClient(self._credentials, subscription_id)
    vms = self._computeClients[subscription_id].virtual_machines.list_all()
    for vm in vms:
      # parse resource group from id: e.g., /resourceGroups/dev2051046045001/providers/
      rgName = re.search('\/resourceGroups\/(.+?)\/providers\/', vm.id).group(1)
      vmName = vm.name
      self.VMs[vmName] = AzureVM(subscription_id, rgName, vmName)

  # Public methods

  def stop_vm(self, vm_name):
    if vm_name not in self.VMs:
      print("VM [{}] not found.".format(vm_name))
      return
    vm = self.VMs[vm_name]
    compute_client = self._computeClients[vm.SubscriptionId]
    deallocate = compute_client.virtual_machines.deallocate(vm.ResourceGroupName, vm.Name)
    print("Stopping VM '{}' ...".format(vm_name))
    deallocate.wait()

  def start_vm(self, vm_name):
    if vm_name not in self.VMs:
      print("VM '{}' not found.".format(vm_name))
      return
    vm = self.VMs[vm_name]
    compute_client = self._computeClients[vm.SubscriptionId]
    start = compute_client.virtual_machines.start(vm.ResourceGroupName, vm.Name)
    print("Starting VM '{}' ...".format(vm_name))
    start.wait()

  def restart_vm(self, vm_name):
    self.stop_vm(vm_name)
    self.start_vm(vm_name)

if __name__ == "__main__":
  TENANT = os.environ['AZURE_TENANT_ID']
  APP_ID = os.environ['AZURE_CLIENT_ID']
  APP_KEY = os.environ['AZURE_CLIENT_SECRET']
  vm_cli = AzureCLI(TENANT, APP_ID, APP_KEY)
  vm_cli.restart_vm('linux4us')
