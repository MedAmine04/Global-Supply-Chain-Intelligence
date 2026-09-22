# ADR-003 — Moteur de règles déclaratif pour le Data Quality, politique "reject only"

## Contexte
FR-02 exige de valider chaque batch Bronze (schéma, doublons, plages
numériques, dates, clés étrangères) et de produire un rapport structuré,
persistant, exploitable par un Data Engineer.

## Problème
Comment implémenter les contrôles qualité de façon à ce qu'ils restent
lisibles et extensibles (une nouvelle entité, une nouvelle règle) sans
dupliquer la logique de comptage/priorisation des rejets à chaque fois ?
Et que fait-on d'une ligne invalide : on la corrige, on la met en
quarantaine, ou on se contente de la signaler ?

## Options considérées

### A. Moteur de règles
1. **Règles codées en dur par entité** (une fonction `check_suppliers()`,
   une fonction `check_orders()`, etc.) — rapide à écrire, mais duplique
   la logique de comptage/agrégation des rejets à chaque entité.
2. **Moteur déclaratif** (`ENTITY_RULES`) : chaque entité déclare ses
   champs requis, ses bornes numériques, ses champs date, ses FK ; un
   seul algorithme de validation s'applique à toutes.

### B. Politique de traitement des lignes invalides
1. **Rejet silencieux** : la ligne invalide disparaît, seul le compteur
   global change.
2. **Reject only + rapport détaillé** : la ligne reste en Bronze
   (immuable, jamais supprimée — cf. principe Bronze), mais elle est
   comptée et catégorisée comme rejetée dans le rapport. Elle ne sera
   simplement pas reprise en Silver (FR-03) tant qu'elle est invalide.
3. **Correction automatique** : par exemple remplacer un `quantity`
   négatif par `null`, ou déduire une date manquante.

## Décision
A2 (moteur déclaratif) + B2 (reject only, pas de correction automatique
en Bronze/Silver à ce stade).

## Justification
- Le moteur déclaratif rend l'ajout d'une entité ou d'une règle triviale
  (une entrée dans `ENTITY_RULES`) plutôt que d'écrire une nouvelle
  fonction de validation à chaque fois — cohérent avec le principe
  "chaque technologie/pattern doit avoir une raison d'être", ici la
  raison est l'extensibilité vers Silver/Gold sans réécriture.
- Le rejet silencieux (B1) est explicitement exclu : le blueprint
  demande un vrai rapport ("Rows processed / Valid / Rejected / motifs"),
  pas juste un total. Sans détail par type d'erreur, un Data Engineer ne
  peut pas diagnostiquer une dérive de qualité (ex. un fournisseur qui
  envoie soudainement des dates invalides).
- La correction automatique (B3) est délibérément exclue à ce stade :
  corriger silencieusement une donnée fausse introduit un risque de
  biais invisible dans les couches Silver/Gold et, en aval, dans le
  modèle ML (Phase 3). Le projet préfère un rejet visible et traçable à
  une correction silencieuse non documentée.

## Compromis / Trade-offs
- Une ligne invalide bloque l'avancement de cette ligne vers Silver tant
  qu'elle n'est pas corrigée à la source — pas de "meilleur effort"
  automatique. Accepté : le volume de rejet reste faible (< 5% observé
  sur le dataset synthétique) et rester strict évite d'introduire des
  règles de correction ad hoc difficiles à auditer.
- Les contrôles de clé étrangère interrogent la table Bronze cible en
  base à chaque run (`SELECT DISTINCT ...`) plutôt que de maintenir un
  cache : acceptable aux volumes actuels, à réévaluer si le volume
  augmente significativement (option : cache en mémoire par run).

## Conséquences
- FR-03 (Silver) devra explicitement filtrer sur les lignes non
  rejetées lors du dernier contrôle qualité de leur batch — cette
  jointure Bronze/DataQualityReport sera actée dans son propre ADR.
- Toute politique de correction automatique future (ex. imputation d'une
  valeur manquante) devra faire l'objet d'un nouvel ADR explicite plutôt
  que d'être ajoutée silencieusement dans le moteur de règles.
