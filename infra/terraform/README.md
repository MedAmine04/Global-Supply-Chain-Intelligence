# Infrastructure Azure (Terraform)

**Non appliqué dans ce projet** — ni `terraform` ni les domaines
HashiCorp ne sont accessibles depuis l'environnement de développement,
et aucune credential Azure n'y est disponible (cf. ADR-014). Ces
fichiers sont écrits pour être corrects, pas vérifiés par une exécution
réelle.

## Utilisation

```bash
cd infra/terraform
terraform init
export TF_VAR_postgres_admin_password="..."  # jamais en dur, jamais commité
terraform plan
terraform apply
```

## Ressources créées

Resource Group, Container Registry (sans identifiants admin statiques —
authentification par identité managée), PostgreSQL Flexible Server,
Log Analytics Workspace, Container App Environment, Container App pour
l'API (1 à 3 replicas, ingress HTTPS).

## Non couvert

Frontend (Container App séparée, même pattern), Kafka/Airflow (hors
périmètre Container Apps — nécessiteraient un cluster dédié ou un
service managé équivalent), secrets réels (Key Vault plutôt que
variables Terraform en clair pour un usage multi-personnes).
