"""Boucle de conversation du Copilot IA (Phase 6).

NOTE D'ENVIRONNEMENT (cf. ADR-012) : aucune clé ANTHROPIC_API_KEY n'est
disponible dans le sandbox de développement — ce module n'a donc pas pu
être testé par un vrai appel LLM ici. Le SDK `anthropic` s'installe et
s'importe correctement (vérifié), et la boucle suit strictement l'API
officielle de tool-use ; ce qui est réellement testé, c'est la couche
sur laquelle repose sa correction : `dispatch_tool_call` (les outils
eux-mêmes, contre les vraies données) — voir tests/test_copilot.py.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.copilot.tools import TOOL_SCHEMAS, dispatch_tool_call
from app.core.config import get_settings

SYSTEM_PROMPT = (
    "Tu es l'assistant IA de Global Supply Chain Intelligence. "
    "Réponds aux questions du Supply Chain Manager en utilisant UNIQUEMENT "
    "les données renvoyées par les outils à ta disposition — n'invente "
    "jamais un chiffre. Pour une question contractuelle ou de politique "
    "interne, utilise search_documents et cite la section source "
    "(ex. 'Section 2 — Late Delivery Penalties'). Si une question sort du "
    "périmètre des outils disponibles, dis-le clairement plutôt que de "
    "deviner. Réponds en français, de façon concise et actionnable."
)

MAX_TOOL_ROUNDS = 4


class MissingApiKeyError(RuntimeError):
    pass


@dataclass
class CopilotResponse:
    answer: str
    # chaque entrée : {"tool": ..., "input": ..., "result": ...}
    tool_calls: list[dict] = field(default_factory=list)


def ask_copilot(db: Session, question: str) -> CopilotResponse:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise MissingApiKeyError(
            "ANTHROPIC_API_KEY non configurée — le Copilot ne peut pas appeler le modèle. "
            "Définissez cette variable d'environnement pour l'activer."
        )

    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages = [{"role": "user", "content": question}]
    tool_calls_log: list[dict] = []

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text")
            return CopilotResponse(answer=text, tool_calls=tool_calls_log)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = dispatch_tool_call(db, block.name, block.input)
            tool_calls_log.append({"tool": block.name, "input": block.input, "result": result})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    return CopilotResponse(
        answer="Je n'ai pas pu conclure dans le nombre d'étapes autorisées.",
        tool_calls=tool_calls_log,
    )
