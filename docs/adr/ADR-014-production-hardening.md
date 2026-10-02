# ADR-014 — Phase 8 : observabilité, sécurité, infrastructure (vérifié ce qui peut l'être)

## Contexte
Dernière phase du planning : monitoring, sécurité, CI/CD, infrastructure
cloud. Comme pour Kafka/Airflow/Terraform précédemment, certaines
briques se vérifient en conditions réelles dans ce sandbox, d'autres
non — traitées avec le même degré d'honnêteté que le reste du projet.

## 1. Observabilité — vérifié en conditions réelles
Métriques Prometheus (`prometheus-client`, middleware FastAPI) exposées
sur `/metrics` : compteur de requêtes par méthode/chemin/statut,
histogramme de latence. **Testé en direct** : un vrai serveur uvicorn
lancé, des requêtes envoyées, `/metrics` vérifié au format Prometheus
réel (`gsci_http_requests_total{method="GET",path="/health",status="200"}`),
plus un test automatisé (`test_metrics_endpoint_exposes_prometheus_format`).
Services `prometheus`/`grafana` ajoutés à `docker-compose.yml` avec
provisioning automatique (datasource + dashboard JSON, 3 panels :
requêtes/sec, latence p95, taux d'erreur 5xx) — non démarrés ici
(pas de Docker dans ce sandbox, cf. ADR-006/007/008), mais le JSON du
dashboard est validé syntaxiquement.

## 2. Audit de sécurité des dépendances — vérifié, avec analyse réelle, pas supposée
`pip-audit` exécuté sur `requirements.txt` : 86 vulnérabilités connues
trouvées initialement, concentrées sur 3 paquets.

### python-dotenv — corrigé (gratuit, sans risque)
Une vulnérabilité (symlink attack sur `set_key()`/`unset_key()`) que ce
projet n'utilise de toute façon jamais (lecture seule via
pydantic-settings). Mis à jour vers 1.2.2 par précaution — aucune
régression (76/76 tests toujours verts après).

### starlette — mis à jour (0.38.6 → 0.48.0), plafond vérifié, pas supposé
FastAPI a été mis à jour (0.115.0 → 0.118.3), ce qui remonte starlette
à 0.48.0. **Vérifié que même la dernière version de FastAPI (0.142.2)
ne permet pas d'aller au-delà de starlette 0.48.0** (testé en
installant cette version : starlette reste capé à 0.48.0) — c'est une
contrainte amont réelle, pas un choix de ne pas chercher plus loin.

Les 6 vulnérabilités restantes à cette version ont été analysées une
par une contre le code réel de ce projet (`grep` sur les routers, pas
une supposition) :
- **DoS via Range header sur `FileResponse`** : aucun endpoint ne sert
  de fichiers (`FileResponse`) dans ce projet — non exposé aujourd'hui.
- **Host/path non validés dans `request.url`** : aucune redirection ni
  logique de cache construite sur `request.url` dans ce projet.
- **SSRF `StaticFiles` via UNC path** : spécifique à Windows ; le
  déploiement cible (Container Apps, Dockerfile `python:3.12-slim`) est
  Linux — non applicable.
- **`HTTPEndpoint` lookup d'attribut arbitraire** : ce projet n'utilise
  que des handlers de fonction via décorateurs FastAPI, jamais la
  classe `HTTPEndpoint` de Starlette — non exposé.
- **Limites `request.form()` non appliquées à l'urlencoded** : aucun
  endpoint n'accepte de formulaire dans ce projet.

**Conclusion assumée** : aucune des vulnérabilités restantes n'a de
surface d'exploitation réelle dans ce projet *aujourd'hui*. Si un futur
FR ajoute un endpoint de téléchargement de fichier, un formulaire, ou
une classe `HTTPEndpoint`, cette analyse doit être refaite — pas
supposée toujours valable.

### mlflow — non corrigé, exposition nulle justifiée (pas de serveur démarré)
63 des 86 vulnérabilités trouvées concernent `mlflow server` (interface
web, API REST, authentification basique) : contournement d'auth,
RCE via désérialisation d'artefacts, traversée de répertoire, CSRF,
SSRF via webhooks, etc. **Ce projet n'exécute jamais `mlflow server`** :
seul `mlflow.set_tracking_uri("file://...")` + `mlflow.start_run()` sont
utilisés (tracking local par fichiers, vérifié par `grep` sur l'usage
réel dans `app/ml/train.py` et `app/cv/train.py`) — aucun processus
serveur, aucun port exposé, aucune de ces vulnérabilités n'a de chemin
d'exploitation. Mettre à jour mlflow risquerait de casser le pipeline
ML/CV déjà testé (46+5 tests) pour un bénéfice de sécurité nul dans ce
mode d'usage. **Si un futur FR déploie un vrai serveur de tracking
MLflow partagé** (plusieurs personnes, accès réseau), cette analyse
devient caduque et la mise à jour (ou une authentification/un
reverse-proxy durci) devient obligatoire.

### pyspark — non corrigé, même raisonnement
L'unique vulnérabilité concerne le Spark History Server (XSS), jamais
démarré par ce projet (Spark local `local[*]` uniquement, cf. ADR-006).

### CI
`pip-audit` ajouté comme étape informative (`|| true`, ne bloque pas le
build) : les findings actuels sont triés comme non exploitables
ci-dessus, les bloquer ferait échouer la CI sans action possible à
court terme ; mais tout **nouveau** finding apparaîtra visiblement dans
les logs à chaque run.

## 3. Conteneurs non-root — écrit, non vérifié par un build réel
`USER app` (backend) et `USER node` (frontend) ajoutés aux Dockerfiles.
**Non vérifié par un `docker build`** (pas de Docker dans ce sandbox,
contrainte déjà établie). Note assumée dans le Dockerfile frontend :
avec le bind-mount de développement (`./frontend:/app`), un décalage
d'UID hôte/conteneur peut bloquer l'écriture — acceptable en dev,
à surveiller si ça gêne réellement un contributeur.

## 4. Infrastructure Azure (Terraform) — écrit, non appliqué
`infra/terraform/main.tf` : Resource Group, Container Registry (sans
identifiants admin statiques), PostgreSQL Flexible Server, Container
App Environment + Container App pour l'API. **Ni `terraform init` ni
`plan` n'ont pu être exécutés** : ni le binaire Terraform ni les
domaines HashiCorp (`releases.hashicorp.com`, `registry.terraform.io`)
ne sont accessibles depuis ce sandbox, et aucune credential Azure n'y
est disponible — vérifié explicitement (403 sur les deux domaines),
pas supposé. Seule une validation syntaxique basique (équilibre des
accolades) a été faite. Kafka, Airflow et le frontend ne sont pas
couverts par ce Terraform (noté dans `infra/terraform/README.md`).

## Conséquences
- Avant un vrai déploiement : exécuter `terraform plan` avec de vraies
  credentials Azure et relire le plan ligne à ligne — ce document ne
  remplace pas cette étape.
- Avant d'ajouter un endpoint de téléchargement de fichier, un
  formulaire, ou toute classe `HTTPEndpoint`, relire la section 2
  (starlette) : l'analyse d'exposition qui y est faite ne tient que
  pour le code actuel.
- Avant de déployer un serveur MLflow partagé entre plusieurs
  personnes : mettre à jour mlflow et relire ses CVE serveur en détail.
