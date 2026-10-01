# ADR-013 — RAG : récupération lexicale sur un corpus synthétique de documents

## Contexte
Phase 7 : répondre à des questions contractuelles/de politique interne
("Que se passe-t-il si un fournisseur livre plus de 5 jours en retard ?")
en citant la source, via le Copilot (ADR-012).

## Pas de vrais documents fournisseurs disponibles
Aucun contrat ni politique interne réels n'existe pour ce projet. Un
petit corpus synthétique mais réaliste a été rédigé (3 documents
Markdown : contrat fournisseur type, politique de transport, politique
qualité des données), cohérent avec les règles déjà codées ailleurs
dans le projet (ex. le seuil de retard de 25% du document reflète la
logique de `supplier_delay_rate`, la section "Rejection vs Correction"
reflète ADR-003).

## Récupération lexicale, pas sémantique (même contrainte qu'ADR-010)
TF-IDF + cosinus, pas d'embeddings — Hugging Face reste inaccessible.
Les limites de cette approche ont été rencontrées et corrigées en
conditions réelles, pas seulement documentées en théorie : une requête
"late delivery penalty" classait initialement en premier résultat
"Section 1 — Delivery Obligations" (répétition de "delivery"/"late")
plutôt que "Section 2 — Late Delivery Penalties" (le bon paragraphe),
parce que les titres de section n'étaient pas inclus dans le texte
indexé. Corrigé en préfixant chaque passage avec son titre de section
avant vectorisation — une vraie amélioration du moteur de recherche,
pas un contournement du test qui avait détecté le problème.

## Découpage
Par paragraphe (séparateur ligne vide), avec extraction du titre de
section (`## ...`) qui précède chaque paragraphe sans ligne vide
intermédiaire — piège rencontré à l'implémentation : le code initial
jetait le texte du paragraphe avec son titre au lieu de les séparer,
donnant 0 chunk chargé. Corrigé ; testé (`test_corpus_loads_with_sections`).

## Intégration au Copilot
`search_documents` est un 5e outil (cf. ADR-012), au même niveau que
`search_incidents` — même mécanique, même limite assumée. Le prompt
système demande explicitement de citer la section source.

## Compromis
- TF-IDF est recalculé à chaque requête sur un corpus de 11 chunks :
  trivial à ce volume, à revoir avec un vrai corpus de contrats
  (indexation persistante, éventuellement pgvector si des embeddings
  deviennent accessibles).
- Le corpus est fictif : aucune réponse du Copilot sur ces questions ne
  doit être interprétée comme un conseil juridique réel.
