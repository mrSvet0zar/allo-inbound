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


# Longueur minimale pour un match par inclusion (évite les faux positifs sur
# des tokens courts, ex: "vue" contenu dans "revue")
_CONTAINMENT_MIN_LEN = 5

# Décote du match par inclusion par rapport à un match exact : un containment
# ne doit jamais l'emporter sur un vrai match exact, même sur un mot courant
# (ex: "consultation" décliné dans 3 entrées doit battre "teleconsultations"
# apparié seulement par inclusion sur une question de tarif).
_CONTAINMENT_DISCOUNT = 0.25


def _doc_frequencies(all_entry_tokens: list[set[str]]) -> dict[str, int]:
    """Nombre d'entrées de la FAQ contenant chaque token (pour la pondération IDF)."""
    freq: dict[str, int] = {}
    for tokens in all_entry_tokens:
        for token in tokens:
            freq[token] = freq.get(token, 0) + 1
    return freq


def _match_score(
    query_tokens: set[str], entry_tokens: set[str], doc_freq: dict[str, int]
) -> float:
    """Score pondéré IDF, tolérant aux variations morphologiques simples.

    Un token de la requête matche s'il est identique à un token de l'entrée,
    OU si l'un contient l'autre (ex: "consultations" est contenu dans
    "teleconsultations") — couvre préfixes ("télé-"), pluriels et dérivés
    courants sans dépendance à une librairie de stemming.

    Chaque match exact est pondéré par 1/doc_freq du token : un mot présent
    dans une seule entrée (très discriminant) pèse plus qu'un mot générique
    présent dans la moitié de la FAQ (ex. "consultation"). Le containment
    n'est utilisé qu'en absence de match exact pour ce token dans cette
    entrée, et toujours décoté — sinon un mot rare apparié seulement par
    inclusion (ex. "consultations" ⊂ "teleconsultations") ferait gagner une
    entrée hors-sujet face à un vrai match exact sur un mot plus commun.
    """
    score = 0.0
    for q_tok in query_tokens:
        if q_tok in entry_tokens:
            score += 1.0 / doc_freq.get(q_tok, 1)
            continue
        if len(q_tok) >= _CONTAINMENT_MIN_LEN:
            best_containment_idf = max(
                (
                    1.0 / doc_freq.get(e_tok, 1)
                    for e_tok in entry_tokens
                    if len(e_tok) >= _CONTAINMENT_MIN_LEN and (q_tok in e_tok or e_tok in q_tok)
                ),
                default=0.0,
            )
            score += best_containment_idf * _CONTAINMENT_DISCOUNT
    return score


class InMemoryKnowledgeBase:
    """Retrieval lexical simple : recouvrement de tokens question+réponse."""

    def __init__(self, entries: list[tuple[str, str]] | None = None):
        source = entries if entries is not None else DEMO_FAQ
        self._entries = [
            (KBEntry(i + 1, q, a), _tokenize(f"{q} {a}")) for i, (q, a) in enumerate(source)
        ]
        self._doc_freq = _doc_frequencies([tokens for _, tokens in self._entries])

    async def search(self, query: str, k: int = 3) -> list[KBEntry]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []
        scored = [
            (_match_score(query_tokens, tokens, self._doc_freq), entry)
            for entry, tokens in self._entries
        ]
        scored = [(score, entry) for score, entry in scored if score > 0]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:k]]

    async def list_all(self) -> list[KBEntry]:
        return [entry for entry, _ in self._entries]
