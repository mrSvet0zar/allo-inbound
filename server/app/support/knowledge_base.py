"""Base de connaissances support (retrieval pour search_knowledge_base).

Même découpage que le Projet 1 (RAG Application) : une interface de retrieval,
des backends interchangeables. Ici deux backends légers adaptés à la voix
(latence-critique, pas de torch dans ce service) :
- InMemoryKnowledgeBase : scoring lexical, dev/tests, FAQ de démo embarquée
- PostgresKnowledgeBase : full-text search français (cf app/db/database.py)

Le backend pgvector + sentence-transformers du Projet 1 peut se brancher
derrière la même interface si le corpus grossit au point que le lexical
ne suffit plus.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol


@dataclass
class KBEntry:
    id: int
    question: str
    answer: str


class KnowledgeBase(Protocol):
    async def search(self, query: str, k: int = 3) -> list[KBEntry]: ...
    async def list_all(self) -> list[KBEntry]: ...


# FAQ de démo : cabinet fictif (le cas d'usage de démonstration)
DEMO_FAQ: list[tuple[str, str]] = [
    (
        "Quels sont vos horaires d'ouverture ?",
        ("Le cabinet est ouvert du lundi au vendredi, de 9h à 12h et de 14h à 18h. "
        "Fermé le week-end et les jours fériés."),
    ),
    (
        "Où se trouve le cabinet et comment venir ?",
        ("Le cabinet se situe au 12 rue de la République à Lyon, à cinq minutes à pied "
        "du métro Bellecour. Un parking public se trouve place des Célestins."),
    ),
    (
        "Quels sont les tarifs et moyens de paiement acceptés ?",
        ("La consultation standard est à 60 euros. Nous acceptons la carte bancaire, "
        "les espèces et les chèques. Les mutuelles sont acceptées sur présentation "
        "de la carte de tiers payant."),
    ),
    (
        "Comment annuler ou déplacer un rendez-vous ?",
        ("Vous pouvez annuler ou déplacer un rendez-vous par téléphone jusqu'à 24 heures "
        "avant l'horaire prévu, sans frais. En dessous de 24 heures, la consultation "
        "peut être facturée."),
    ),
    (
        "Faut-il apporter des documents pour une première consultation ?",
        ("Pour une première consultation, apportez votre carte vitale, votre carte de "
        "mutuelle et, si vous en avez, vos derniers examens ou comptes rendus médicaux."),
    ),
    (
        "Proposez-vous des téléconsultations ?",
        ("Oui, des téléconsultations sont possibles le mardi et le jeudi après-midi. "
        "Le lien de connexion est envoyé par SMS après la prise de rendez-vous."),
    ),
]

_WORD_RE = re.compile(r"[a-z0-9]{3,}")
# Mots trop fréquents pour discriminer (français courant + domaine)
_STOPWORDS = {
    "les", "des", "une", "est", "pour", "vous", "avec", "dans", "que", "qui",
    "quel", "quels", "quelle", "quelles", "comment", "sont", "vos", "votre",
}


def _tokenize(text: str) -> set[str]:
    # Normalise les accents pour matcher "téléconsultation" ~ "teleconsultation"
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return {w for w in _WORD_RE.findall(text) if w not in _STOPWORDS}


class InMemoryKnowledgeBase:
    """Retrieval lexical simple : recouvrement de tokens question+réponse."""

    def __init__(self, entries: list[tuple[str, str]] | None = None):
        source = entries if entries is not None else DEMO_FAQ
        self._entries = [
            (KBEntry(i + 1, q, a), _tokenize(f"{q} {a}")) for i, (q, a) in enumerate(source)
        ]

    async def search(self, query: str, k: int = 3) -> list[KBEntry]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        scored = [
            (len(query_tokens & tokens) / len(query_tokens), entry)
            for entry, tokens in self._entries
        ]
        scored = [(score, entry) for score, entry in scored if score > 0]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:k]]

    async def list_all(self) -> list[KBEntry]:
        return [entry for entry, _ in self._entries]
