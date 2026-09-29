"""Ingestion de la base de connaissances support depuis un fichier métier.

Deux formats acceptés :
- Markdown : chaque `## Question ?` ouvre une entrée, le texte qui suit
  (jusqu'au prochain titre) est la réponse. Le contenu avant le premier
  `##` est ignoré (titre du document, notes...).
- CSV : colonnes `question,answer` (en-têtes requis, insensibles à la casse).

Le retrieval en production est le full-text français de Postgres
(app/db/database.py — colonne tsv générée automatiquement à l'insertion) :
ingérer du contenu suffit, aucun calcul d'embedding n'est nécessaire.

Usage :
    python -m scripts.ingest_kb kb/cabinet_exemple.md --replace
    python -m scripts.ingest_kb faq.csv --dry-run
"""

import argparse
import asyncio
import csv
import io
import sys
from pathlib import Path

import asyncpg

from app.config import get_settings

Entry = tuple[str, str]  # (question, réponse)


def parse_markdown(text: str) -> list[Entry]:
    entries: list[Entry] = []
    question: str | None = None
    answer_lines: list[str] = []

    def push() -> None:
        if question is not None:
            answer = "\n".join(answer_lines).strip()
            if answer:
                entries.append((question, answer))

    for line in text.splitlines():
        if line.startswith("## "):
            push()
            question = line[3:].strip()
            answer_lines = []
        elif question is not None:
            answer_lines.append(line)
    push()
    return entries


def parse_csv(text: str) -> list[Entry]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    columns = {name.lower().strip(): name for name in reader.fieldnames}
    if "question" not in columns or "answer" not in columns:
        raise ValueError(
            f"Colonnes 'question' et 'answer' requises, trouvées : {reader.fieldnames}"
        )
    entries = []
    for row in reader:
        question = (row[columns["question"]] or "").strip()
        answer = (row[columns["answer"]] or "").strip()
        if question and answer:
            entries.append((question, answer))
    return entries


def parse_file(path: Path) -> list[Entry]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        return parse_csv(text)
    if path.suffix.lower() in (".md", ".markdown"):
        return parse_markdown(text)
    raise ValueError(f"Format non géré : {path.suffix} (attendu .md ou .csv)")


async def ingest(dsn: str, entries: list[Entry], replace: bool) -> int:
    conn = await asyncpg.connect(dsn, timeout=15)
    try:
        async with conn.transaction():
            if replace:
                await conn.execute("DELETE FROM knowledge_base")
            await conn.executemany(
                "INSERT INTO knowledge_base (question, answer) VALUES ($1, $2)", entries
            )
        return await conn.fetchval("SELECT COUNT(*) FROM knowledge_base")
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="fichier .md ou .csv à ingérer")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="vide la table avant d'insérer (déploiement d'un nouveau contenu complet)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="affiche les entrées parsées sans rien insérer"
    )
    args = parser.parse_args()

    entries = parse_file(args.file)
    if not entries:
        print("Aucune entrée trouvée dans le fichier — rien à faire.")
        return 1

    print(f"{len(entries)} entrées parsées depuis {args.file} :")
    for question, answer in entries:
        print(f"  • {question}  ({len(answer)} caractères de réponse)")

    if args.dry_run:
        print("\n--dry-run : aucune insertion effectuée.")
        return 0

    dsn = get_settings().database_url
    if not dsn:
        print("DATABASE_URL absente (cf .env) — impossible d'ingérer.", file=sys.stderr)
        return 1

    total = asyncio.run(ingest(dsn, entries, replace=args.replace))
    mode = "remplacée par" if args.replace else "complétée de"
    print(f"\nBase de connaissances {mode} {len(entries)} entrées — total en base : {total}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
