"""Agent conversationnel Claude pour la voix.

Boucle streaming avec tool_use : les phrases sont émises au fil de l'eau
(async generator) pour que le TTS démarre sans attendre la réponse complète.
Modèle : Haiku 4.5 (latence, cf CLAUDE.md), prompt caching sur le system
prompt et les définitions d'outils.
"""

import logging
import random
import re
from collections.abc import AsyncIterator
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import AsyncAnthropic

from app.llm.toolbox import ALL_SLOW_TOOLS, ALL_TOOL_DEFINITIONS, AgentToolbox

logger = logging.getLogger(__name__)

PARIS_TZ = ZoneInfo("Europe/Paris")

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024  # réponses vocales courtes
MAX_TOOL_ROUNDS = 6

# Relances naturelles prononcées avant un outil lent (réduit la latence perçue).
# Variées pour ne pas sonner robotique sur un appel avec plusieurs recherches.
FILLER_SENTENCES = {
    "fr": [
        "Un instant, je vérifie.",
        "Je regarde ça tout de suite.",
        "Deux secondes, je consulte.",
        "Laissez-moi vérifier ça.",
    ],
    "en": [
        "One moment, let me check.",
        "I'll look that up right away.",
        "Just a second, checking.",
        "Let me verify that for you.",
    ],
}

_FALLBACK_ERROR_SENTENCE = {
    "fr": "Excusez-moi, je rencontre une difficulté. Je vous transfère à un conseiller.",
    "en": "I'm sorry, I'm having trouble. Let me transfer you to a human agent.",
}

# Message d'accueil prononcé par l'agent dès l'ouverture du stream (c'est lui
# qui amorce la conversation, l'appelant ne devrait jamais avoir à dire "allô ?"
# dans le vide). Une phrase par entrée : découpage déjà prêt pour le TTS.
GREETING_SENTENCES = {
    "fr": [
        "Bonjour, assistante vocale du cabinet, que puis-je faire pour vous ?",
    ],
    "en": [
        "Hello, this is the clinic's voice assistant, how can I help you?",
    ],
}

SYSTEM_PROMPT = """Tu es l'assistant vocal téléphonique d'un cabinet de démonstration.
Tu parles au téléphone : tes réponses sont ORALES, courtes (1 à 3 phrases),
sans listes, sans markdown, sans emojis. Nombres et heures en toutes lettres
naturelles ("quatorze heures trente").

Style oral naturel :
- Commence chaque réponse par une courte interjection (deux à quatre mots,
  ex. "Bien sûr.", "D'accord.", "Très bien.", "Ah, je vois.") suivie d'un
  point, puis enchaîne avec le contenu. Varie ces interjections, n'utilise
  jamais deux fois la même dans un même appel.
- Utilise des tournures parlées naturelles (contractions, "voilà", "donc"),
  jamais de style écrit ou de formulations administratives.
- Varie tes formulations d'un tour à l'autre : ne répète pas la même phrase
  de relance ou de confirmation mot pour mot plusieurs fois dans un appel.
- Glisse de temps en temps — pas à chaque phrase — un léger marqueur oral
  ("alors", "voyons", "hmm", "euh") comme le ferait une vraie personne au
  téléphone. Avec parcimonie : une conversation, pas une caricature.
- Si l'historique montre que ta réponse précédente a été interrompue par
  l'appelant, ne reprends pas ce que tu disais : réponds directement à ce
  qu'il vient de dire, en tenant compte de ce que tu as déjà eu le temps
  de dire.

Tu gères deux types de demandes :
1. Les RENDEZ-VOUS : vérifier les disponibilités, réserver, déplacer,
   retrouver, annuler.
2. Le SUPPORT : répondre aux questions pratiques (horaires, adresse, tarifs,
   documents, téléconsultation...) via la base de connaissances, et créer un
   ticket de suivi si la réponse n'y figure pas.

Au décroché, l'appelant a déjà entendu ton message d'accueil : « {greeting} »
Ne te représente pas et ne redis pas bonjour — la première phrase de
l'appelant exprime généralement déjà son besoin, réponds-y directement.

Règles impératives :
- Avant de réserver, déplacer ou annuler, répète les détails et demande une
  confirmation orale explicite ("Je confirme : ... c'est bien ça ?").
  N'appelle book_appointment, modify_appointment ou cancel_appointment
  qu'après un "oui" clair.
- Vérifie toujours les disponibilités (check_availability) avant de proposer
  un horaire.
- Quand tu proposes des créneaux, n'en énonce jamais plus de trois d'un coup
  (ex. "j'ai neuf heures, onze heures ou quatorze heures") même si
  check_availability en renvoie beaucoup plus — précise que d'autres sont
  disponibles si besoin. Une énumération trop longue est pénible à l'oral et
  empêche l'appelant de répondre facilement.
- Si l'appelant répond de façon ambiguë ou incomplète (ex. tu n'as capté
  qu'un fragment), pose une question courte et ciblée pour clarifier ce point
  précis plutôt que de tout répéter depuis le début.
- Pour toute question d'information, cherche d'abord dans la base de
  connaissances (search_knowledge_base). Ne réponds jamais de mémoire. Si la
  base ne contient pas la réponse, propose un ticket de suivi ou un transfert.
- Si l'appelant demande un humain, ou pour toute réclamation, litige ou sujet
  sensible, appelle escalate_to_human immédiatement sans insister.
- Si tu n'as pas compris, fais répéter poliment plutôt que de deviner.
- Ne promets jamais de service qui n'existe pas : il n'y a NI confirmation
  par SMS, NI par mail, ni rappel automatique. La confirmation orale pendant
  l'appel est la seule qui existe.
- Reste dans ton périmètre : pour toute demande hors sujet, dis-le simplement
  et propose ton aide sur les rendez-vous.

{language_directive}

La date d'aujourd'hui est {today}."""

# Directive de langue insérée dans le prompt. La base de connaissances et les
# données du calendrier restent en français quelle que soit la langue choisie
# par l'appelant — l'agent traduit à la volée ce qu'il en dit.
_LANGUAGE_DIRECTIVES = {
    "fr": "Réponds exclusivement en français.",
    "en": (
        "Respond exclusively in English, even though the knowledge base, tool "
        "results and appointment data are in French — translate anything you "
        "relay from them into natural English."
    ),
}

# Fin de phrase : ponctuation forte suivie d'un espace. Une ponctuation en
# toute fin de buffer n'émet pas (le delta suivant peut continuer, ex: "3." + "50") ;
# c'est flush() qui récupère la dernière phrase quand le stream est terminé.
_SENTENCE_END = re.compile(r"([.!?…]+)\s+")


class SentenceBuffer:
    """Accumule les deltas de texte et émet des phrases complètes."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        sentences = []
        while match := _SENTENCE_END.search(self._buf):
            end = match.end(1)
            sentence = self._buf[:end].strip()
            self._buf = self._buf[end:].lstrip()
            if sentence:
                sentences.append(sentence)
        return sentences

    def flush(self) -> str | None:
        rest = self._buf.strip()
        self._buf = ""
        return rest or None


# Note ajoutée à l'historique quand une réponse a été coupée par l'appelant :
# sans elle, le texte déjà prononcé disparaîtrait de l'historique et l'agent
# ne saurait ni ce qu'il a dit, ni qu'il a été interrompu.
_INTERRUPTION_NOTES = {
    "fr": "…(interrompu par l'appelant à ce moment)",
    "en": "…(interrupted by the caller at this point)",
}


class VoiceAgent:
    """Un agent par appel : conserve l'historique de conversation."""

    def __init__(self, client: AsyncAnthropic, toolbox: AgentToolbox, language: str = "fr"):
        self._client = client
        self._toolbox = toolbox
        self._language = language if language in _LANGUAGE_DIRECTIVES else "fr"
        self._messages: list[dict] = []
        # Phrases émises depuis le dernier ajout à l'historique : si le tour
        # est interrompu (tâche annulée par le barge-in), elles sont
        # réinjectées comme réponse partielle au début du tour suivant.
        self._pending_spoken: list[str] = []
        self.tool_calls_count = 0

    def _flush_interrupted_speech(self) -> None:
        """Réinjecte dans l'historique ce qui a été prononcé avant interruption."""
        if not self._pending_spoken:
            return
        spoken = " ".join(self._pending_spoken)
        self._pending_spoken = []
        self._messages.append(
            {"role": "assistant", "content": f"{spoken} {_INTERRUPTION_NOTES[self._language]}"}
        )

    async def run_turn(self, user_text: str) -> AsyncIterator[str]:
        """Traite un tour de parole de l'appelant et émet des phrases de réponse."""
        self._flush_interrupted_speech()
        self._messages.append({"role": "user", "content": user_text})

        for _ in range(MAX_TOOL_ROUNDS):
            buffer = SentenceBuffer()
            async with self._client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT.format(
                            today=datetime.now(tz=PARIS_TZ).date().isoformat(),
                            language_directive=_LANGUAGE_DIRECTIVES[self._language],
                            greeting=" ".join(GREETING_SENTENCES[self._language]),
                        ),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=ALL_TOOL_DEFINITIONS,
                messages=self._messages,
            ) as stream:
                async for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and event.delta.type == "text_delta"
                    ):
                        for sentence in buffer.feed(event.delta.text):
                            self._pending_spoken.append(sentence)
                            yield sentence
                response = await stream.get_final_message()

            if rest := buffer.flush():
                self._pending_spoken.append(rest)
                yield rest

            self._messages.append({"role": "assistant", "content": response.content})
            # Le contenu complet du round est maintenant dans l'historique
            self._pending_spoken = []

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_uses:
                return

            # Relance naturelle si un outil lent va s'exécuter et que l'agent
            # n'a encore rien dit dans ce round
            said_something = any(
                b.type == "text" and b.text.strip() for b in response.content
            )
            if not said_something and any(b.name in ALL_SLOW_TOOLS for b in tool_uses):
                filler = random.choice(FILLER_SENTENCES[self._language])
                self._pending_spoken.append(filler)
                yield filler

            tool_results = []
            for block in tool_uses:
                self.tool_calls_count += 1
                logger.info("Outil %s(%s)", block.name, block.input)
                result = await self._toolbox.execute(block.name, dict(block.input))
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )
            self._messages.append({"role": "user", "content": tool_results})

        logger.warning("MAX_TOOL_ROUNDS atteint, fin de tour forcée")
        fallback = _FALLBACK_ERROR_SENTENCE[self._language]
        self._pending_spoken.append(fallback)
        yield fallback

    @property
    def escalation_requested(self) -> str | None:
        return self._toolbox.escalation_requested

    @property
    def toolbox(self) -> AgentToolbox:
        return self._toolbox
