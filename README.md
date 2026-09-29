# Allo-IA — Assistant Vocal Téléphonique Inbound

Assistant vocal IA qui répond à un **vrai numéro de téléphone** et gère deux cas
d'usage : **prise de rendez-vous** (vérifier, réserver, modifier, annuler) et
**support client** (FAQ via RAG, tickets, escalade vers un humain).

> ✅ Projet complet et **déployé en production** : serveur temps réel sur
> Railway (EU West), dashboard sur Vercel, base Supabase, numéro Twilio
> français actif. Démo live : appeler le numéro, choisir sa langue (FR/EN),
> et converser.

## Architecture

```
Appel entrant → menu de langue (DTMF, FR/EN) → annonce de transparence IA
             → Twilio Media Streams (WebSocket, μ-law 8kHz)
             → Serveur FastAPI (orchestration, asyncio)
             → Deepgram STT streaming (endpointing = fin de tour de parole)
             → Claude Haiku 4.5 (tool_use : RDV, RAG support, escalade,
               raccrochage — exécution SPÉCULATIVE sur les transcripts
               provisoires, effets de bord gelés jusqu'à confirmation)
             → TTS ElevenLabs par WebSocket stream-input (voix native par
               langue, prosodie continue, connexion pré-ouverte)
             → envoi cadencé au débit de lecture réel (AudioPacer)
             → Retour audio vers l'appelant — barge-in à tout moment

             → PostgreSQL (RDV, tickets, base de connaissances, call_logs)
             → API admin (lecture seule) → Dashboard Next.js
```

Le serveur temps réel (`server/`) maintient un WebSocket ouvert pendant toute
la durée de chaque appel → Railway plutôt que du serverless. Le dashboard
admin (`dashboard/`, Next.js, consultation seule) est déployé séparément sur
Vercel et consomme l'API admin en lecture seule du serveur temps réel.

## Décisions d'architecture & optimisation de la latence

Pipeline modulaire STT→LLM→TTS (plutôt que speech-to-speech natif) : chaque
étage est observable, testable et remplaçable — le compromis est la latence,
optimisée étage par étage. Latence moyenne par tour (silence confirmé →
premier octet audio), mesurée sur appels téléphoniques réels :

| Étape | Latence moyenne |
|---|---|
| Pipeline initial (HTTP par phrase, région US testée) | 2468 ms |
| Retour EU West + interjections courtes + prompt caching | 1426 ms |
| **+ exécution spéculative + TTS WebSocket + pré-connexion** | **1071 ms** ✅ (objectif < 1200 ms) |

Les tours où la spéculation aboutit (transcript provisoire == final)
descendent à **420-713 ms**. Leviers principaux, dans l'ordre d'impact :

1. **Exécution spéculative** : la génération Claude démarre pendant que
   l'appelant parle encore (transcripts provisoires Deepgram) ; l'audio et
   les outils (réservations !) sont gelés jusqu'à la confirmation de fin de
   parole, avec rollback d'historique si la spéculation est démentie.
2. **TTS WebSocket stream-input** : premier octet à ~135 ms (vs ~240-390 ms
   en HTTP par phrase), prosodie continue sur toute la réponse, connexion
   suivante pré-ouverte en arrière-plan.
3. **AudioPacer** : l'envoi est cadencé au débit de lecture réel (8000 o/s) —
   indispensable au barge-in : sans lui, une longue réponse est déjà
   entièrement dans le buffer Twilio quand l'appelant tente de couper.
4. **Interjection courte en ouverture de réponse** ("D'accord.") : le TTS
   démarre dès la première ponctuation pendant que la suite se génère.
5. **Prompt caching** (system + outils) et **région serveur mesurée** (EU
   West bat US East pour ce compte, contrairement à l'intuition — mesuré).

Le réalisme conversationnel : barge-in avec **mémoire des interruptions**
(l'agent sait ce qu'il a eu le temps de dire), relances naturelles variées
pendant les recherches, marqueurs oraux légers, jamais plus de trois
créneaux énoncés d'affilée, et **raccrochage par l'agent** en fin de
conversation (outil `end_call`).

## Métriques

- Latence moyenne par tour : **1071 ms** (objectif < 1200 ms) ; tours avec
  spéculation réussie : 420-713 ms
- Campagne de scénarios : **16/16 réussis (100 %**, objectif > 80 %) —
  rejouée avant chaque évolution du prompt
- 123 tests unitaires et d'intégration
- Appels réels de bout en bout validés : prise de RDV avec négociation et
  changements d'avis, questions support via base de connaissances, ticket
  pour question hors base, refus de double réservation avec proposition
  d'alternatives, raccrochage automatique

## Limites connues

- La reconnaissance vocale reste sensible aux noms propres ("Ganivet" →
  "Ganillet"), aux accents et au bruit de fond ; un bruit peut produire un
  micro-tour parasite.
- La voix la plus expressive d'ElevenLabs (`eleven_v4_turbo`) n'est pas
  disponible sur leur WebSocket : le projet privilégie la continuité de
  prosodie et la latence (`eleven_flash_v2_5` + session continue).
- Le modèle peut glisser sur une confirmation d'horaire (confondre 14h et
  14h30) — l'appelant peut toujours corriger, et la validation côté outil
  empêche toute double réservation.
- La base de connaissances de démo est volontairement minimale (6 entrées) ;
  le retrieval lexical (pondération IDF) suffira à cette échelle, le backend
  pgvector du projet RAG se branche derrière la même interface au-delà.

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

Voir [CLAUDE.md](CLAUDE.md) pour le détail des 5 phases, toutes livrées et
déployées. Pistes d'évolution : contexte métier réel (FAQ fournie par un
vrai cabinet), filtrage des micro-tours parasites issus du bruit, et le
projet frère **outbound** (appels sortants), volontairement découplé.
