# ACRFP — Terraform only (RG + AKS via small local modules)

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "prefix" {
  type    = string
  default = "acrfp"
}

variable "location" {
  type        = string
  default     = "centralindia"
  description = "centralindia works on this subscription; westeurope blocked new AKS"
}

variable "node_count" {
  type    = number
  default = 1
}

variable "vm_size" {
  type        = string
  default     = "Standard_B2s_v2"
  description = "Burstable B-series; B2s not available in centralindia"
}

variable "ssh_public_key" {
  type        = string
  default     = ""
  description = "Your OpenSSH public key (e.g. contents of ~/.ssh/id_rsa.pub). Empty = no linux_profile (current cluster)."
}

variable "admin_username" {
  type    = string
  default = "acrfpadmin"
}

locals {
  tags = {
    project = "acrfp"
    managed = "terraform"
  }
}

module "rg" {
  source   = "./modules/rg"
  name     = "${var.prefix}-rg"
  location = var.location
  tags     = local.tags
}

module "aks" {
  source              = "./modules/aks"
  name                = "${var.prefix}-aks"
  location            = module.rg.location
  resource_group_name = module.rg.name
  dns_prefix          = var.prefix
  node_count          = var.node_count
  vm_size             = var.vm_size
  ssh_public_key      = var.ssh_public_key
  admin_username      = var.admin_username
  tags                = local.tags
}

# Keep existing Azure resources when moving into modules (no destroy/recreate).
moved {
  from = azurerm_resource_group.main
  to   = module.rg.azurerm_resource_group.this
}

moved {
  from = azurerm_kubernetes_cluster.main
  to   = module.aks.azurerm_kubernetes_cluster.this
}

output "resource_group" {
  value = module.rg.name
}

output "location" {
  value = module.rg.location
}

output "aks_name" {
  value = module.aks.name
}

output "get_credentials_command" {
  value = "az aks get-credentials --resource-group ${module.rg.name} --name ${module.aks.name} --overwrite-existing"
}
