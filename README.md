# Allo-IA — Assistant Vocal Téléphonique Inbound

Assistant vocal IA qui répond à un **vrai numéro de téléphone** et gère deux cas
d'usage : **prise de rendez-vous** (vérifier, réserver, modifier, annuler) et
**support client** (FAQ via RAG, tickets, escalade vers un humain).

> 🚧 Projet portfolio — Phases 1 à 5 implémentées (téléphonie → agent
> conversationnel → deux cas d'usage → fiabilité → dashboard admin). Reste :
> déploiement réel (Fly.io/Railway + Vercel).

## Architecture

```
Appel entrant → Twilio Media Streams (WebSocket, μ-law 8kHz)
             → Serveur FastAPI (orchestration, asyncio)
             → Deepgram STT streaming (endpointing = fin de tour de parole)
             → Claude (tool_use : RDV, RAG support, escalade)
             → TTS streaming (ElevenLabs) phrase par phrase, barge-in
             → Retour audio vers l'appelant

             → PostgreSQL (RDV, tickets, base de connaissances, call_logs)
             → API admin (lecture seule) → Dashboard Next.js
```

Le serveur temps réel (`server/`) maintient un WebSocket ouvert pendant toute
la durée de chaque appel → destiné à Fly.io/Railway (pas de serverless). Le
dashboard admin (`dashboard/`, Next.js, consultation seule) est déployé
séparément, typiquement sur Vercel, et consomme l'API admin en lecture seule
du serveur temps réel.

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

## Dashboard admin

Consultation en lecture seule des appels (avec transcript), des rendez-vous
à venir, des tickets ouverts et des alertes basiques (dérive de latence,
taux d'escalade anormal), plus la page de transparence/consentement
publique.

```bash
cd dashboard
npm install
cp .env.example .env.local   # NEXT_PUBLIC_API_URL, NEXT_PUBLIC_ADMIN_KEY
npm run dev
```

Le serveur temps réel doit tourner en parallèle et autoriser l'origine du
dashboard via `DASHBOARD_ORIGINS` (cf `server/.env.example`) ; si
`ADMIN_API_KEY` est configurée côté serveur, le dashboard doit envoyer la
même valeur dans `NEXT_PUBLIC_ADMIN_KEY`.

## Observabilité

Chaque appel est loggé (durée, tours, outils, résultat, latence moyenne) en
base (ou en mémoire sans `DATABASE_URL`). `app/observability/alerting.py`
calcule deux signaux à partir des 100 derniers appels — taux d'escalade
anormal (> 30 %) et dérive de latence (moyenne > 1.2s, P95 > 2s) — affichés
en bandeau sur le dashboard.

## Roadmap

Voir [CLAUDE.md](CLAUDE.md) pour le détail des 5 phases. Il reste le
déploiement réel : serveur temps réel sur Fly.io/Railway, dashboard sur
Vercel, base Supabase, et les clés API (Twilio, Deepgram, ElevenLabs,
Anthropic) à provisionner.
