# Infrastructure Azure (Phase 8 — Production)
#
# NON APPLIQUÉ ni même `terraform init`-é dans ce projet : ni le binaire
# terraform ni les domaines HashiCorp (releases.hashicorp.com,
# registry.terraform.io) ne sont accessibles depuis l'environnement de
# développement, et aucune credential Azure n'y est disponible — cf.
# ADR-014. Ces fichiers sont écrits pour être corrects et utilisables
# tels quels par quelqu'un ayant Terraform + un abonnement Azure, pas
# vérifiés par une exécution réelle ici.

terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.100"
    }
  }
}

provider "azurerm" {
  features {}
}

variable "project_name" {
  default = "gsci"
}

variable "environment" {
  default = "production"
}

variable "location" {
  default = "westeurope"
}

variable "postgres_admin_password" {
  description = "Mot de passe admin PostgreSQL (fournir via TF_VAR_postgres_admin_password, jamais en dur)"
  sensitive   = true
  type        = string
}

resource "azurerm_resource_group" "main" {
  name     = "${var.project_name}-${var.environment}-rg"
  location = var.location
}

resource "azurerm_container_registry" "main" {
  name                = "${var.project_name}${var.environment}acr"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false # auth via identité managée, pas d'identifiants admin statiques
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "${var.project_name}-${var.environment}-pg"
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = "16"
  administrator_login    = "gsci_admin"
  administrator_password = var.postgres_admin_password
  storage_mb             = 32768
  sku_name               = "B_Standard_B1ms" # dev/staging ; prévoir GP_* pour une vraie charge de prod
  zone                   = "1"
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.project_name}-${var.environment}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "main" {
  name                       = "${var.project_name}-${var.environment}-env"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

resource "azurerm_container_app" "api" {
  name                         = "${var.project_name}-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  template {
    container {
      name   = "api"
      image  = "${azurerm_container_registry.main.login_server}/gsci-api:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }
    }
    min_replicas = 1
    max_replicas = 3
  }

  secret {
    name  = "database-url"
    value = "postgresql+psycopg://gsci_admin:${var.postgres_admin_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/gsci"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }
}

output "api_url" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "container_registry_login_server" {
  value = azurerm_container_registry.main.login_server
}
