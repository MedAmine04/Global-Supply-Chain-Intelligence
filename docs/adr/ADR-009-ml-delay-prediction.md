# ADR-009 — Prédiction de retard : split temporel, prévention du leakage, résultats assumés

## Contexte
Phase 3 du planning : un modèle prédisant si une expédition arrivera en
retard (FR-11), suivi des expériences (FR-12), et exposition des
expéditions à risque via l'API (FR-13). Le planning demande de comparer
Logistic Regression, Random Forest et XGBoost sur Precision/Recall/F1/
ROC-AUC/matrice de confusion.

## Décisions

### 1. Aucune feature ne doit utiliser une information postérieure au départ de l'expédition
C'est le piège n°1 d'un projet ML supply chain. Un "taux de retard
historique du fournisseur" calculé en incluant l'expédition elle-même
(ou des expéditions futures) donne un modèle excellent en test mais
inutilisable en production, puisque cette information n'existe pas
encore au moment de la prédiction réelle.

`supplier_delay_rate` et `previous_incidents_count` sont donc calculés
strictement à partir des expéditions *antérieures* du même fournisseur
(`shift(1)` + `expanding()` en pandas : jamais la ligne courante, jamais
le futur). **Vérifié par un test explicite**
(`test_second_shipment_reflects_first_shipment_outcome_not_its_own`) :
une expédition à l'heure dont la précédente était en retard doit avoir
`supplier_delay_rate == 1.0`, pas `0.0` — ce que donnerait une fuite.

### 2. Split temporel, pas aléatoire
Les 80% d'expéditions les plus anciennes servent à l'entraînement, les
20% les plus récentes au test. Un split aléatoire mélangerait passé et
futur des deux côtés et masquerait les erreurs qu'un vrai déploiement
rencontrerait (prédire l'avenir avec un modèle qui n'a vu que le
passé).

### 3. Valeur de repli du cold start calculée sur le train uniquement
Un fournisseur sans historique n'a pas de `supplier_delay_rate`
calculable. La valeur de repli utilisée vient de la seule moyenne du
jeu d'entraînement — utiliser celle du test serait une fuite
d'information sur des données que le modèle ne doit voir qu'à
l'évaluation (**testé** : `test_fill_cold_start_uses_train_mean_not_test_mean`).

### 4. MLflow en mode fichier local, pas de serveur
Contrairement à Kafka (ADR-007), MLflow supporte un mode de tracking
purement local (`file://mlruns/`) sans processus serveur — vérifié
avant de s'engager. Les 3 modèles sont loggés (paramètres, métriques,
artefact) dans l'expérience `shipment_delay_prediction`. Un vrai
serveur MLflow avec Model Registry serait la cible de la Phase 8
(Production), pas nécessaire pour comparer des modèles en développement.

### 5. Rééquilibrage de classes sur les trois modèles
Environ 21% de retards : sans rééquilibrage, un modèle peut afficher un
bon ROC-AUC tout en prédisant presque toujours "pas de retard" au seuil
0.5. `class_weight="balanced"` (LR, RandomForest) et `scale_pos_weight`
(XGBoost) sont appliqués aux trois.

## Ce qui a mal tourné en cours de route (et ce que ça a appris)

**Premier entraînement : ROC-AUC ≈ 0.49 sur les trois modèles — pas
mieux que le hasard.** La cause n'était ni le feature engineering ni le
choix de modèle : le générateur de données synthétiques injectait les
retards de façon totalement aléatoire (`random.random() < 0.22`),
indépendamment de toute autre colonne. Il n'existait donc littéralement
aucun signal à apprendre — aucun modèle n'aurait pu faire mieux.

**Correction à la source** : le générateur fait maintenant dépendre la
probabilité de retard de la fiabilité du fournisseur, du mode de
transport et de la distance (coefficients arbitraires mais documentés
dans le code, non ajustés a posteriori pour améliorer le score). C'est
un choix méthodologique assumé : un dataset synthétique doit contenir
les relations qu'on veut vérifier que le modèle sait retrouver — sans
quoi un mauvais score ne dit rien sur la qualité du pipeline.

**Second problème : rappel de 0.007 pour RandomForest** malgré un ROC-AUC
correct, parce que je n'avais pas appliqué `class_weight` à ce modèle
(seulement à LR). Corrigé (décision 5).

**Trois vrais bugs de code attrapés par les tests ou l'exécution**, tous
du même type (cas limite vide/cold start) :
- une expédition non livrée recevait une valeur factice `0` comme
  résultat, ce qui aurait faussé le taux de retard historique d'une
  *autre* expédition du même fournisseur (remplacé par `NaN`, ignoré
  par `expanding().mean()`) ;
- un DataFrame pandas vide sans colonnes (aucune expédition livrée en
  historique) cassait l'accès par nom de colonne — même piège que celui
  rencontré côté Spark (ADR-006), résolu par un schéma de colonnes
  explicite ;
- `DimTransport` non importé au niveau module dans le repository
  analytics (détecté au premier appel réel de l'API, pas par le lint).

## Résultats obtenus (dataset synthétique "medium", ~8 700 expéditions livrées)

| Modèle | Precision | Recall | F1 | ROC-AUC |
|---|---|---|---|---|
| Logistic Regression | 0.377 | 0.614 | 0.467 | **0.571** |
| Random Forest | 0.397 | 0.393 | 0.395 | 0.561 |
| XGBoost | 0.357 | 0.389 | 0.373 | 0.533 |

**Ces résultats sont modestes, et c'est assumé.** Un ROC-AUC de 0.57 est
un signal réel (nettement au-dessus du 0.49 du premier essai sans
relation causale) mais faible : les coefficients du générateur ont été
choisis volontairement modérés, pour ne pas fabriquer un problème
artificiellement facile. Ne pas présenter ces chiffres comme la
performance d'un modèle "de production" — ils valident que le pipeline
fonctionne et retrouve un signal, pas qu'il prédit bien des retards
réels. Le meilleur modèle est Logistic Regression, ce qui est cohérent
avec un dataset dont les relations injectées sont linéaires (pas de
raison qu'un modèle non linéaire fasse mieux ici).

## Compromis / Trade-offs
- Le seuil de décision reste 0.5 : avec le rééquilibrage de classes,
  près de la moitié des expéditions en cours sont marquées "à risque
  élevé" (4366 / 8815 au dernier run). Un vrai déploiement calibrerait
  ce seuil selon le coût métier d'un faux positif vs. faux négatif —
  décision qui appartient au métier, pas à ce code.
- Un seul modèle "gagnant" est sauvegardé (fichier `.joblib` + métadonnées
  JSON) au lieu d'un vrai Model Registry versionné : suffisant pour
  développer, insuffisant pour de la production (Phase 8).
- Pas de monitoring de dérive du modèle (FR ultérieur, hors périmètre v1).
- Explicabilité SHAP (FR-14) non implémentée dans cette itération.

## Conséquences
- FR-13 (liste des expéditions à risque) est exposée par
  `/api/predictions/at-risk` ; l'affichage dans le dashboard React
  reste à faire.
- Tout ré-entraînement futur devra conserver les trois garde-fous (pas
  de fuite temporelle dans les features, split temporel, repli
  cold-start calculé sur le train) — testés, donc protégés contre une
  régression silencieuse.
