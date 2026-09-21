"""Outils support client / SAV (RAG + tickets)."""

from typing import Any

SUPPORT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Recherche dans la base de connaissances du cabinet (horaires, adresse, "
            "tarifs, documents, téléconsultation...). À appeler pour toute question "
            "d'information AVANT de répondre — ne jamais inventer une réponse."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "La question de l'appelant"},
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "create_support_ticket",
        "description": (
            "Crée un ticket de support quand la question n'a pas de réponse dans la base "
            "de connaissances ou nécessite un suivi. Annoncer à l'appelant qu'il sera "
            "recontacté."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "resume": {"type": "string", "description": "Résumé clair de la demande"},
                "priorite": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Priorité : high uniquement si urgent pour l'appelant",
                },
            },
            "required": ["resume", "priorite"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]

SUPPORT_SLOW_TOOLS = {"search_knowledge_base", "create_support_ticket"}
