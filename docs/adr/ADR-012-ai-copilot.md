# ADR-012 — AI Copilot : tool-use Anthropic, non vérifié en direct (Gemini bloqué, pas de clé Anthropic)

## Contexte
Phase 6 : un Copilot conversationnel répondant aux questions du Supply
Chain Manager en s'appuyant sur les données réelles (pas d'invention de
chiffres — principe explicite du blueprint).

## Architecture
`app/copilot/tools.py` définit 4 outils (schéma Anthropic tool-use) qui
appellent directement les services déjà écrits et testés (analytics,
ml_predict, nlp.search) — aucune logique métier nouvelle, seulement un
pont nom d'outil → fonction réelle (`dispatch_tool_call`).
`app/copilot/agent.py` porte la boucle de conversation : envoie la
question à Claude avec les outils disponibles, exécute les appels
d'outils demandés, renvoie leurs résultats au modèle, jusqu'à une
réponse finale en texte.

## Contrainte d'environnement (vérifiée deux fois, pas supposée)
Aucune clé API n'était configurée dans ce sandbox. Au cours de la
session, l'utilisateur a partagé une clé présentée comme une clé
Gemini — **traitée comme potentiellement compromise du seul fait
d'avoir été collée dans la conversation** (jamais écrite dans un
fichier ni un commit ; recommandation de révocation faite à
l'utilisateur). Indépendamment de la validité de cette clé, une
vérification réseau directe a confirmé que
`generativelanguage.googleapis.com` (l'API Gemini) est bloqué par le
pare-feu de ce sandbox ("Host not in allowlist"), alors que
`api.anthropic.com` **répond normalement** (erreur d'authentification
standard, pas un blocage réseau) — l'architecture est donc restée sur
l'API Anthropic, alignée avec le reste de ce document et directement
testable si une clé Anthropic devient disponible.

## Ce qui a été vérifié ici
- Le SDK `anthropic` s'installe et s'importe correctement.
- **`dispatch_tool_call` est testé contre les vraies données** (7
  tests) : chaque outil appelle la bonne fonction de service et
  retourne les données réelles du pipeline (KPI, performance
  fournisseur, expéditions à risque, recherche d'incidents) — c'est la
  couche dont dépend la correction de toute réponse du Copilot, qu'elle
  soit ou non appelée par un vrai LLM.
- `ask_copilot` échoue explicitement et clairement
  (`MissingApiKeyError`) si `ANTHROPIC_API_KEY` n'est pas configurée —
  testé — plutôt que de planter avec une erreur SDK peu claire.

## Ce qui n'a PAS été vérifié ici
- La boucle de conversation réelle (`ask_copilot` avec une vraie clé) :
  l'enchaînement question → choix d'outil par le modèle → exécution →
  réponse finale n'a pas pu être exécuté de bout en bout. Sa correction
  repose sur le respect strict de l'API tool-use documentée d'Anthropic
  et sur `dispatch_tool_call` (testé) — pas sur une exécution observée.
- Le comportement du modèle face à une question hors périmètre des 4
  outils (le prompt système le lui demande explicitement, mais ce n'est
  pas vérifié empiriquement).

**Pour vérifier ces points**, avec une vraie clé Anthropic :
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m app.cli ask-copilot "Quels fournisseurs ont le plus de retards ?"
```

## Décisions de conception
- **Le modèle ne voit jamais la base de données directement** : il ne
  peut agir qu'au travers des 4 outils exposés, chacun retournant des
  données déjà calculées par des services testés — aucune requête SQL
  générée par le LLM, aucune possibilité d'halluciner un chiffre qui ne
  vienne pas d'un de ces appels.
- **`tool_calls` renvoyé avec la réponse** (API et CLI) : le frontend
  affiche "Données utilisées" en repli, pour que l'utilisateur puisse
  vérifier ce qui a réellement été interrogé — cohérent avec le
  principe du blueprint de ne jamais présenter une réponse IA sans les
  données qui la sous-tendent.
- **4 outils, pas plus** : KPI, fournisseurs, expéditions à risque,
  recherche d'incidents couvrent les questions les plus probables du
  persona Supply Chain Manager sans complexifier le prompt système.

## Conséquences
- Toute nouvelle capacité du Copilot (ex. lancer un nouveau contrôle
  qualité, déclencher un ré-entraînement) devra passer par un nouvel
  outil explicite dans `TOOL_SCHEMAS` — jamais par un accès direct à la
  base ou au système de fichiers depuis le modèle.
- La Phase 7 (RAG) réutilisera probablement ce même Copilot en lui
  ajoutant un outil de recherche documentaire, plutôt que de construire
  un second agent séparé.
