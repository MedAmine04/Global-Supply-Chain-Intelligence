# ADR-010 — NLP sur les incidents : TF-IDF + spaCy, sans modèles Hugging Face

## Contexte
Phase 4 du planning : classification des incidents, NER, embeddings,
recherche sémantique sur les descriptions d'incidents.

## Contrainte d'environnement (vérifiée, pas supposée)
`huggingface.co` renvoie 403 depuis l'environnement de développement :
ni transformers pré-entraînés, ni sentence-transformers (embeddings).
GitHub reste accessible, ce qui permet spaCy (modèle `en_core_web_sm`
publié en release GitHub). Conséquences assumées :
- **Classification** : TF-IDF (1-2 grammes) + régression logistique,
  comparée à un baseline "classe majoritaire" — pas de fine-tuning BERT.
- **NER** : hybride. Regex pour la référence d'expédition (format d'ID
  connu), règle pour la durée ("three days" → 3), spaCy pour le lieu.
- **"Recherche sémantique" : NON réalisée.** `search_incidents` est une
  recherche *lexicale* (TF-IDF + cosinus) : "truck engine breakdown"
  retrouve "vehicle breakdown" grâce au seul mot `breakdown`, pas parce
  qu'elle comprend que truck ≈ vehicle. L'interface est conçue pour être
  remplacée par des embeddings + pgvector sans toucher aux appelants.
- **Embeddings et sentiment : non implémentés** (le planning les cite).

## Le piège des données synthétiques, une deuxième fois
Les descriptions d'incidents du générateur étaient `fake.sentence()`,
du texte aléatoire sans lien avec le type — aucun classifieur n'aurait
pu apprendre quoi que ce soit (même erreur que le générateur de retards,
ADR-009). Corrigé avant tout entraînement : gabarits par type, avec
vocabulaire volontairement partagé entre types (ex. "customs" dans
CUSTOMS_DELAY et DOCUMENTATION) et ~10 % de textes génériques.

## Résultats (1663 incidents, split aléatoire stratifié 80/20)
- Baseline classe majoritaire : accuracy 0.183
- TF-IDF + LogReg : accuracy 0.928, macro-F1 0.930
- Le plafond est proche de 90 % par construction : les ~10 % de textes
  génériques ("Incident logged for SHP-…") sont inclassables.

**Ces chiffres valident le pipeline, pas la généralisation.** Le texte
est produit par 3 gabarits par type que j'ai écrits : un classifieur
qui retrouve des gabarits n'est pas la preuve qu'il classerait de vrais
rapports d'incident, plus variés et bruités.

Extraction d'entités, avec ce qu'elle prouve vraiment :
- référence d'expédition : 1663/1663 corrects, et durée : 100 % des
  textes qui en mentionnent une. **Peu informatif** : ce sont des règles
  appliquées à mes propres gabarits.
- lieu (spaCy) : ~83 % des textes contenant une ville. spaCy rate des
  noms inventés par Faker ("Samanthaview", "Hoganfort"). Seule mesure
  non triviale, et biaisée : sur de vraies villes le taux serait
  probablement meilleur, mais ce n'est pas démontré ici.

## Décisions
- Split **aléatoire** (et non temporel comme ADR-009) : les textes sont
  indépendants, sans dépendance temporelle créant une fuite.
- Identifiants d'expédition remplacés par un jeton neutre avant
  vectorisation : l'ID est un bruit unique par incident, le garder
  ferait apprendre des identifiants par cœur.
- Résultats persistés (`incident_insights`, upsert idempotent, testé).

## Compromis
- Le classifieur ne renvoie que le type le plus probable ; pas de
  seuil de confiance ni de rejet des textes génériques.
- La recherche recalcule TF-IDF à chaque requête : acceptable à ~1 700
  incidents, à remplacer par un index (pgvector) si le volume croît.

## Conséquences
- Compatibilité de dépendances à surveiller en Phase 5 : spaCy 3.7
  impose `numpy<2`, alors que les OpenCV récents exigent `numpy>=2`.
