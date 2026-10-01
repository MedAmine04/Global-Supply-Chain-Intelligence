"""Récupération documentaire pour le RAG (Phase 7).

Récupération LEXICALE (TF-IDF + cosinus), pas sémantique — même
contrainte et même choix que pour la recherche d'incidents
(app/nlp/search.py, ADR-010) : aucun modèle d'embeddings n'est
accessible depuis cet environnement (Hugging Face bloqué). Une requête
comme "What if a supplier is late?" ne retrouvera le bon paragraphe que
si ses mots (ou leurs bigrammes) apparaissent dans le texte — pas de
compréhension du sens.

Découpage par paragraphe (séparateur `\\n\\n`) plutôt que par fenêtre de
tokens glissante : les documents sources (contrats, politiques) sont
déjà structurés en sections courtes et auto-suffisantes, un découpage
plus complexe n'apporterait rien ici.
"""

from dataclasses import dataclass
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs_corpus"


@dataclass
class DocumentChunk:
    source: str  # nom de fichier
    section: str  # titre de section (## ...), si trouvé
    text: str


@dataclass
class RetrievedChunk(DocumentChunk):
    score: float


def load_and_chunk_corpus(docs_dir: Path = DOCS_DIR) -> list[DocumentChunk]:
    chunks = []
    for path in sorted(docs_dir.glob("*.md")):
        current_section = path.stem
        for paragraph in path.read_text().split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            lines = paragraph.splitlines()
            # Un bloc peut commencer par un titre ("## Section ...") suivi
            # directement de son texte, sans ligne vide entre les deux —
            # format réel des documents sources. Il faut extraire le
            # titre ET garder le texte qui suit, pas jeter tout le bloc.
            if lines[0].startswith("#"):
                current_section = lines[0].lstrip("#").strip()
                lines = lines[1:]
            body = "\n".join(lines).strip()
            if body:
                chunks.append(DocumentChunk(source=path.name, section=current_section, text=body))
    return chunks


def retrieve_relevant_chunks(
    query: str, chunks: list[DocumentChunk] | None = None, limit: int = 3
) -> list[RetrievedChunk]:
    chunks = chunks if chunks is not None else load_and_chunk_corpus()
    if not chunks or not query.strip():
        return []

    # Le titre de section est indexé avec le corps du texte : un titre
    # comme "Late Delivery Penalties" est hautement informatif et ne
    # doit pas être ignoré par la recherche — sans ça, une requête sur
    # "penalty" peut classer en tête une section dont le corps répète
    # simplement plus souvent des mots communs ("delivery", "late"),
    # découvert concrètement en testant ce module (cf. ADR-013).
    corpus = [f"{c.section}. {c.text}" for c in chunks]
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
    matrix = vectorizer.fit_transform(corpus)
    scores = cosine_similarity(vectorizer.transform([query]), matrix).ravel()

    ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:limit]
    return [
        RetrievedChunk(
            source=chunks[i].source, section=chunks[i].section,
            text=chunks[i].text, score=round(float(scores[i]), 4),
        )
        for i in ranked
        if scores[i] > 0
    ]
