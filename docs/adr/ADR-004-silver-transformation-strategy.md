# ADR-004 — Silver : filtrage strict sur le rapport qualité, upsert sur clé métier

## Contexte
FR-03 doit produire une couche Silver typée, propre et dédupliquée à
partir de Bronze, en s'appuyant sur les résultats de FR-02 (Data
Quality). Silver reçoit des batches au fil du temps (ré-ingestions,
corrections amont) : il faut donc aussi décider comment une même entité
métier (ex. `SUP-000002`) est traitée si elle est ingérée plusieurs fois.

## Problème
1. Comment savoir, au moment de la transformation Silver, quelles lignes
   Bronze d'un batch sont valides sans dupliquer la logique de
   validation de FR-02 ?
2. Que faire quand un batch ré-ingère une entité déjà présente en
   Silver — écraser, empiler, ou ignorer ?

## Options considérées

### Question 1 — Source de vérité sur la validité
1. **Revalider dans Silver** avec les mêmes règles que FR-02 —
   duplication de logique, risque de divergence entre le rapport affiché
   au Data Engineer et ce qui est réellement chargé.
2. **S'appuyer sur le `DataQualityReport` déjà persisté** (FR-02),
   en y stockant la liste des IDs Bronze rejetés (`rejected_row_ids`),
   et lever une erreur explicite si aucun rapport n'existe pour le batch.

### Question 2 — Gestion des ré-ingestions
1. **Accumuler** (insert-only, comme Bronze) — mais Silver doit être
   dédupliqué par définition (cf. blueprint : "Clean / validated /
   déduplicated"), donc contraire à l'objectif de la couche.
2. **Upsert sur la clé métier** (`supplier_id`, `order_id`, ...) : la
   ligne existante est mise à jour si l'ID métier existe déjà, sinon
   créée.

## Décision
1. Option 2 : le rapport qualité est la seule source de vérité sur la
   validité d'une ligne Bronze pour la transformation Silver. Si aucun
   rapport n'existe pour le `(entity, batch_id)` demandé, la
   transformation échoue explicitement (`QualityCheckMissingError`)
   plutôt que de deviner ou de tout accepter.
2. Option 2 : upsert sur la clé métier.

## Justification
- Réutiliser le rapport FR-02 évite toute divergence entre "ce que le
  Data Engineer a vu dans le rapport qualité" et "ce qui a réellement
  été chargé en Silver" — un même calcul de validité, une seule fois.
- L'échec explicite si le contrôle qualité n'a pas été exécuté empêche
  un batch non validé d'atteindre Silver par accident (ex. un script mal
  ordonné) : le pipeline reste sûr même mal utilisé.
- L'upsert sur clé métier permet de gérer proprement les corrections en
  amont (un fournisseur corrige son `reliability_score`) sans dupliquer
  la ligne ni exiger une purge manuelle de Silver à chaque ré-ingestion —
  démontré par un test dédié
  (`test_transform_upserts_on_second_run_without_duplicating`).

## Compromis / Trade-offs
- L'upsert est fait ligne par ligne en Python (requête + comparaison),
  pas en SQL `ON CONFLICT` natif : plus lisible et plus simple à tester,
  mais moins performant à très gros volume. Accepté pour les volumes de
  développement (dataset "small"/"medium") ; à réévaluer en Phase 2
  quand Spark prendra en charge les transformations à plus grande
  échelle.
- Une ligne dont une valeur ne peut pas être castée vers son type Silver
  cible (cas non prévu par les règles FR-02 actuelles) est chargée avec
  `None` pour ce champ plutôt que de faire échouer tout le batch, et
  comptée dans `rows_cast_errors` pour rester visible. Ce cas ne devrait
  normalement jamais se produire si FR-02 est complet — sa présence
  éventuelle signale un trou dans les règles de qualité à combler.

## Conséquences
- Toute nouvelle règle de validation ajoutée en FR-02 doit couvrir tout
  champ que FR-03 caste en type strict, pour éviter les `rows_cast_errors`
  silencieux.
- FR-04 (Gold, prochaine étape) pourra s'appuyer sur Silver en confiance :
  les données y sont déjà typées, validées et dédupliquées.
