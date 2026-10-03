# AKS module (simple — one node pool)

variable "name" {
  type = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "dns_prefix" {
  type = string
}

variable "node_count" {
  type    = number
  default = 1
}

variable "vm_size" {
  type    = string
  default = "Standard_B2s_v2"
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "ssh_public_key" {
  type        = string
  default     = ""
  description = "Optional SSH public key for node linux_profile (set at create time; changing later may recreate AKS)."
}

variable "admin_username" {
  type    = string
  default = "acrfpadmin"
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  dns_prefix          = var.dns_prefix

  default_node_pool {
    name            = "nodepool1"
    node_count      = var.node_count
    vm_size         = var.vm_size
    os_disk_size_gb = 30
  }

  dynamic "linux_profile" {
    for_each = var.ssh_public_key != "" ? [1] : []
    content {
      admin_username = var.admin_username
      ssh_key {
        key_data = var.ssh_public_key
      }
    }
  }

  identity {
    type = "SystemAssigned"
  }

  tags = var.tags
}

output "name" {
  value = azurerm_kubernetes_cluster.this.name
}

output "id" {
  value = azurerm_kubernetes_cluster.this.id
}
