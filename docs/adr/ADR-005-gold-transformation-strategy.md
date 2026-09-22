# ADR-005 — Gold : transformation full-refresh, dimensions dénormalisées dans les faits

## Contexte
FR-04 doit produire un vrai modèle dimensionnel (star schema) à partir de
Silver : dimensions (`dim_supplier`, `dim_product`, `dim_warehouse`,
`dim_transport`, `dim_date`) et faits (`fact_orders`, `fact_shipments`,
`fact_incidents`), exploitables par le dashboard (FR-07 à FR-09) et,
plus tard, par le feature engineering ML (FR-11).

## Problèmes à trancher
1. Gold doit-il transformer par batch (comme Bronze → Silver) ou sur
   l'état courant complet de Silver ?
2. `fact_shipments` doit-il porter uniquement `warehouse_sk`/`order_id`,
   ou dénormaliser aussi `supplier_sk`/`product_sk` depuis la commande
   associée ?
3. Le retard d'une expédition (`is_delayed`, `delay_days`) doit-il être
   calculé à l'écriture (Gold) ou à la lecture (requête API/dashboard) ?

## Décisions

### 1. Transformation full-refresh (pas de scope par batch)
Gold relit l'intégralité des tables Silver à chaque run, plutôt que de ne
traiter qu'un batch Silver récent.

**Justification** : Silver est déjà dédupliqué (un `supplier_id` = une
seule ligne, mise à jour en place par upsert). Une transformation Gold
"par batch Silver" n'aurait pas de sens, puisqu'un batch Silver n'existe
plus en tant que tel après upsert — seul l'état courant compte. Un run
complet reste largement suffisant aux volumes de développement (< 10k
lignes par entité) ; il sera réévalué si Spark est introduit en Phase 2
pour du calcul distribué à plus grand volume.

### 2. Dénormalisation de supplier/product dans `fact_shipments`
`fact_shipments` porte directement `supplier_sk` et `product_sk` (copiés
depuis la commande associée), en plus de `warehouse_sk` et
`transport_sk`.

**Justification** : le blueprint métier positionne explicitement
`fact_shipments` entre `dim_supplier` et `dim_product` dans son schéma
(section 9), pas seulement relié à `dim_warehouse`. Cette dénormalisation
est aussi directement motivée par FR-11 (prédiction de retard) : la
feature `supplier_delay_rate` nécessite d'agréger les retards par
fournisseur *au niveau expédition*, ce qui serait une jointure
supplémentaire vers `fact_orders` à chaque requête si l'information
n'était pas déjà présente sur le fait. Le coût (une colonne dupliquée,
resynchronisée à chaque run Gold) est faible et assumé.

### 3. `is_delayed` / `delay_days` précalculés en Gold
Ces deux mesures sont calculées une fois lors de la transformation Gold
et stockées, plutôt que recalculées à chaque requête.

**Justification** : ce sont les mesures les plus consultées du projet
(dashboard FR-07/FR-09, feature target du modèle ML FR-11) ; les
précalculer évite de dupliquer `(actual_delivery_date -
expected_delivery_date)` dans chaque requête SQL et dans le futur code
ML, et garantit une définition unique et cohérente du "retard" dans tout
le projet.

## Autres décisions structurantes
- **Ordre d'exécution strict** : dimensions puis faits. Un fait dont la
  dimension référencée n'existe pas encore (jamais censé arriver si
  l'ordre est respecté) est **ignoré et compté** (`skipped`), pas une
  erreur bloquante — défense en profondeur plutôt que confiance aveugle
  dans l'ordonnancement.
- **`dim_date` sans clé de substitution entière (YYYYMMDD)** : la date
  elle-même sert de clé primaire. Un entier `20240315` n'apporterait un
  gain de performance que sur des volumes bien supérieurs à ceux de ce
  projet ; la date en clé reste plus lisible en debug SQL.
- **`dim_transport` statique** (les 4 valeurs `road/sea/air/rail` sont
  codées en dur) plutôt que dérivée dynamiquement de Silver : le domaine
  de valeurs est fixe et connu à l'avance côté métier.

## Conséquence observée (validée en run réel)
Un effet de bord attendu et vérifié : des commandes valides en Silver
mais référençant un fournisseur ou produit **rejeté par FR-02** sont
automatiquement exclues de `fact_orders` (comptées en `skipped`), parce
que la dimension correspondante n'existe pas. C'est le comportement
désiré — la qualité se propage naturellement à travers les couches
sans logique supplémentaire à écrire.

## Compromis / Trade-offs
- Le full-refresh relit des lignes Silver qui n'ont pas changé depuis le
  dernier run Gold (pas de détection de delta) : acceptable au volume
  actuel, à réévaluer en Phase 2.
- La dénormalisation de `supplier_sk`/`product_sk` dans `fact_shipments`
  introduit une redondance avec `fact_orders` : si une commande change
  de fournisseur après coup (cas métier rare, non prévu dans le dataset
  synthétique actuel), il faudra veiller à ce que `fact_shipments` soit
  re-transformé après `fact_orders` pour rester cohérent — déjà garanti
  par l'ordre d'exécution de `transform_gold()`.

## Conséquences
- Le dashboard (FR-07 à FR-09) peut interroger `fact_shipments` /
  `fact_orders` directement sans jointure complexe pour les KPI de base.
- FR-11 (ML) pourra calculer `supplier_delay_rate` par un simple
  `GROUP BY supplier_sk` sur `fact_shipments`, sans jointure vers
  `fact_orders`.
