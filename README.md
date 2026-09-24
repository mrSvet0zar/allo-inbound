# Allo-IA — Assistant Vocal Téléphonique Inbound

Assistant vocal IA qui répond à un **vrai numéro de téléphone** et gère deux cas
d'usage : **prise de rendez-vous** (vérifier, réserver, modifier, annuler) et
**support client** (FAQ via RAG, tickets, escalade vers un humain).

> 🚧 Projet en cours — Phase 1 (fondations téléphonie) implémentée.

## Architecture

```
Appel entrant → Twilio Media Streams (WebSocket, μ-law 8kHz)
             → Serveur FastAPI (orchestration, asyncio)
             → Deepgram STT streaming (endpointing = fin de tour de parole)
             → Claude (tool_use : RDV, RAG support, escalade)   [Phase 2]
             → TTS streaming phrase par phrase                   [Phase 2]
             → Retour audio vers l'appelant
```

Le serveur temps réel maintient un WebSocket ouvert pendant toute la durée de
chaque appel → déployé sur Fly.io/Railway (pas de serverless). Le dashboard
admin (Next.js, consultation) sera déployé séparément sur Vercel.

## Transparence & conformité

- L'appelant est informé **dès le décroché** qu'il parle à un assistant IA et
  que l'appel est transcrit (obligations légales FR / RGPD).
- Escalade humaine disponible à tout moment ("passez-moi quelqu'un").
- Confirmation orale avant toute action engageante (réservation, annulation).

## Développement local

```bash
cd server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # remplir les clés
uvicorn app.main:app --reload
```

Exposer le serveur à Twilio en dev : `ngrok http 8000`, puis configurer le
webhook Voice du numéro Twilio sur `https://<ngrok>/voice` et `PUBLIC_HOST`
dans `.env` sur l'hôte ngrok.

### Tests

```bash
cd server && pytest
```

### Scénarios conversationnels rejoués

Avant chaque déploiement, 16 scénarios types (RDV simple, créneau indisponible,
annulation, support, escalade, hors-sujet...) sont rejoués contre le vrai agent
(Claude réel, pipeline audio court-circuité) avec vérification des outils
appelés, du résultat et des confirmations orales — plus la latence texte par
tour (objectif global < 1.2s, cf CLAUDE.md) :

```bash
cd server && python -m eval.run_scenarios          # nécessite ANTHROPIC_API_KEY
python -m eval.run_scenarios --only rdv_simple     # un seul scénario
python -m eval.run_scenarios --json report.json    # export détaillé
```

## Roadmap

Voir [CLAUDE.md](CLAUDE.md) — phases : téléphonie ✅ → boucle conversationnelle
(Claude + TTS + barge-in) → deux cas d'usage → latence/fiabilité → dashboard.
