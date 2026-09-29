# ADR-011 — Détection de dommages : CNN maison, images synthétiques, instabilité découverte et corrigée

## Contexte
Phase 5 du planning : détecter les colis endommagés à partir de photos,
et faire remonter ce signal comme contribution au score de risque
d'une expédition.

## Contrainte d'environnement (vérifiée)
Aucune source de poids pré-entraînés ni de dataset d'images n'est
accessible depuis l'environnement de développement :
- `download.pytorch.org` (poids ResNet, wheels PyTorch CPU) → 403
- `kaggle.com`, `zenodo.org` (datasets d'images de colis réels,
  type Parcel3D) → 403
- PyTorch installé sans l'index CPU dédié tire par défaut des paquets
  CUDA ; l'exécution échoue ensuite faute de bibliothèques CUDA
  présentes (`libcublasLt.so` introuvable) — confirmé en pratique, pas
  supposé.

**Décision** : TensorFlow-CPU (s'installe et s'exécute sans dépendance
CUDA) et OpenCV pour un générateur d'images synthétiques de colis, avec
un chargeur de dossier (`app/cv/dataset.py`) permettant de brancher de
vraies photos plus tard sans changer le reste du pipeline.

## Le CNN a d'abord été instable — découverte et correction en trois temps
**1er entraînement (1200 images, pas de seed fixée)** : le modèle
prédisait presque tout "endommagé" (precision 0.50, recall 1.0) —
aucune discrimination réelle.

**Diagnostic** : la courbe d'entraînement montrait un surapprentissage
classique (accuracy train 78%, val bloquée ~50%) : le modèle mémorisait
le bruit par-image plutôt que le signal de dommage. Corrigé par
augmentation légère (flip, rotation — label-preserving) et davantage de
dropout.

**2e problème, plus subtil** : avec 3000 images, la validation
grimpait jusqu'à 89% d'accuracy vers l'epoch 23 puis s'effondrait à 66%
par la fin — instabilité d'entraînement, pas de manque de signal. Sans
seed fixée sur l'initialisation des poids TensorFlow, deux runs sur les
mêmes données pouvaient converger vers des optima complètement
différents. Corrigé par `tf.random.set_seed()`, `ReduceLROnPlateau`, et
`EarlyStopping(restore_best_weights=True)` avec une patience plus large.

**3e découverte, pendant l'écriture des tests** : en dessous d'environ
3000 images (testé à 500 et 800, avec jusqu'à 35 epochs), le modèle
collapse de façon fiable vers "toujours normal" (precision/recall/F1 =
0) — **ce n'est pas un problème de budget d'epochs mais une vraie limite
du pipeline à ce volume**. Le test de non-régression
(`test_training_pipeline_learns_real_signal`) utilise donc l'échelle
recommandée (3000 images, 50 epochs, ~3 min) plutôt qu'une version
réduite qui ne prouverait rien de fiable — exclu de la suite rapide via
`@pytest.mark.slow` (`pytest -m "not slow"` en CI).

## Résultats finaux (3000 images synthétiques, split 80/20 stratifié)
Deux runs avec la même seed : F1 0.805 et F1 0.870 (precision/recall
dans les deux cas nettement au-dessus du hasard). **Pas parfaitement
reproductible au bit près** malgré la seed fixée — TensorFlow a des
sources de non-déterminisme sur CPU au-delà de l'initialisation des
poids (ordonnancement des threads, opérations parallèles). Les deux
runs restent dans une zone de performance cohérente ; ce n'est pas
présenté comme un résultat figé à la décimale près.

**Ce que ces chiffres valident** : le pipeline (génération, CNN,
entraînement, évaluation) fonctionne et apprend un signal visuel réel
(dents, déchirures, taches, coins écrasés) sur les images synthétiques.
**Ce qu'ils ne valident pas** : la performance sur de vraies photos de
colis, dont la variabilité (éclairage, angle, arrière-plan réel) dépasse
largement celle du générateur.

## Décisions de conception
- **CNN maison (3 blocs conv, ~50k paramètres)**, pas de transfer
  learning : cohérent avec l'absence de poids pré-entraînés
  accessibles, et proportionné à des images 64×64.
- **Générateur avec distracteurs bénins** (ombre, autocollant, pli) et
  dommages de sévérité variable (certains subtils) : un dataset où le
  dommage serait toujours flagrant n'aurait rien prouvé sur la capacité
  du modèle à discriminer un signal réel.
- **Split aléatoire stratifié**, pas temporel : les images sont
  indépendantes (contrairement aux expéditions, ADR-009).

## Périmètre explicitement non traité
- **Pas d'intégration au score de risque Gold** (`fact_shipments`) : le
  générateur ne lie pas ses images à un `shipment_id` réel du dataset
  supply chain — les images sont un flux à part, scorées via
  `score-images --folder`. Relier une image à une expédition précise
  (upload, stockage) est un vrai morceau de travail (Phase 6/7,
  stockage de fichiers) plutôt qu'une extension mineure de cet ADR.
- Pas de Grad-CAM ni d'explication visuelle de la zone détectée comme
  endommagée (le blueprint le suggère implicitement via "confidence" et
  "risk contribution").

## Conséquences
- `python -m app.cli train-damage-classifier --image-folder <dossier>`
  permet de ré-entraîner sur de vraies photos (structure `normal/` /
  `damaged/`) sans changer le code, seulement la source de données.
- Attention dépendances (déjà noté en ADR-010) : TensorFlow et OpenCV
  récents exigent `numpy<2`, cohérent avec spaCy — vérifié, aucune
  régression sur la suite existante après installation.
