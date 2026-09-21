# CLAUDE.md — Allo-IA (Assistant Vocal Téléphonique Inbound)

## 🎯 Vision du Projet

**Allo-IA** est un assistant vocal qui répond au téléphone (vrai numéro, vrais appels)
et gère deux cas d'usage : **prise de rendez-vous** (vérifie les disponibilités, réserve,
modifie, annule) et **support client** (répond aux questions via une base de connaissances,
crée un ticket si besoin, escalade vers un humain si nécessaire).

**Positionnement portfolio :** c'est le premier projet du portfolio à toucher la voix
temps réel — un domaine technique très différent des précédents (latence critique,
streaming audio bidirectionnel, gestion des interruptions, téléphonie réelle). C'est
aussi la démo la plus spectaculaire à faire tester en live à un recruteur : "appelez ce
numéro".

**Note de scope :** ce projet couvre uniquement l'**inbound** (répondre aux appels).
Un projet séparé traitera l'**outbound** (appels sortants avec objectif, prospection) —
volontairement découplé pour livrer quelque chose de complet plutôt que deux moitiés.

---

## ⚠️ Contraintes Légales & Éthiques (Non-Négociables)

1. **Transparence obligatoire en début d'appel.** Le tout premier message vocal doit
   informer clairement l'appelant qu'il parle à un assistant IA (pas se faire passer
   pour un humain) : ex. *"Bonjour, vous êtes en relation avec l'assistant vocal de
   [Entreprise]. Comment puis-je vous aider ?"* — c'est aussi une obligation légale en
   France pour l'utilisation de voix synthétiques dans un contexte commercial.
2. **Consentement à l'enregistrement.** Si les appels sont enregistrés/transcrits pour
   amélioration du service, l'appelant doit en être informé explicitement en début
   d'appel (obligation RGPD/CNIL sur l'enregistrement téléphonique).
3. **Escalade humaine toujours disponible.** L'appelant doit pouvoir demander à parler
   à un humain à tout moment ("passez-moi quelqu'un") — l'agent doit reconnaître cette
   demande et transférer l'appel plutôt que d'insister à résoudre lui-même.
4. **Pas de décision définitive sur des sujets sensibles.** Pour le support, l'agent
   répond aux questions factuelles (horaires, procédures, infos produit) mais escalade
   systématiquement les réclamations complexes, litiges, ou demandes nécessitant un
   jugement humain (remboursement important, cas juridique, etc.).
5. **Confirmation explicite avant toute action engageante.** Avant de finaliser une
   réservation/annulation, l'agent répète les détails et demande confirmation orale
   ("Je confirme : rendez-vous mardi 14h, c'est bien ça ?") — réduit les erreurs et
   rassure l'appelant qu'il a été bien compris.

---

## 🏗️ Stack Technique

| Composant | Choix | Justification |
|---|---|---|
| Téléphonie | Twilio Voice + Media Streams | Standard du marché, numéro réel, streaming audio bidirectionnel via WebSocket |
| Serveur temps réel | Python (FastAPI + WebSockets, asyncio) | Cohérent avec FaceInsight, gère bien les connexions longues et le streaming |
| Speech-to-Text | Deepgram (Nova-3, streaming) | Latence très faible (~300ms), bonne gestion du français, endpointing intégré (détecte fin de tour de parole) |
| LLM | Claude (Haiku 4.5 pour la rapidité, Sonnet en fallback si la requête est complexe) | Function calling natif, cohérent avec le reste du portfolio |
| Text-to-Speech | ElevenLabs (Turbo v2.5, streaming) ou Cartesia Sonic | Streaming phrase par phrase (pas d'attente de la réponse complète), voix naturelles en français |
| Base de données | PostgreSQL (Supabase) | RDV, base de connaissances support, logs d'appels |
| RAG support | Réutilise l'architecture du Projet 1 (RAG Application) | pgvector, retrieval sur la base de connaissances FAQ/procédures |
| Déploiement serveur | Fly.io ou Railway (PAS serverless/Vercel) | Connexions WebSocket longues (durée d'un appel) incompatibles avec les limites d'exécution serverless |
| Dashboard admin | Next.js (Vercel) | Séparé du serveur temps réel — consultation des RDV, transcripts, base de connaissances |

**Point d'architecture important :** contrairement à Prisme-IA (routes API stateless sur
Vercel), le serveur qui gère les appels doit tourner en continu et maintenir une connexion
WebSocket ouverte pendant toute la durée de chaque appel. Ça ne peut pas être une fonction
serverless classique — d'où le choix de Fly.io/Railway pour cette partie spécifique,
pendant que le dashboard admin (consultation, pas de temps réel) reste sur Vercel.

---

## 🔄 Pipeline Temps Réel

```
Appel entrant (Twilio)
        │
        ▼
Twilio Media Stream (WebSocket, audio μ-law 8kHz par chunks)
        │
        ▼
Serveur FastAPI (relais + orchestration)
        │
        ▼
Deepgram STT (streaming, avec endpointing)
        │  ← détecte quand l'appelant a fini de parler
        ▼
Claude (streaming, avec tool_use)
        │  ← function calling : check_availability, book_appointment,
        │     search_knowledge_base, escalate_to_human, etc.
        ▼
TTS streaming (ElevenLabs/Cartesia) — synthèse phrase par phrase,
dès qu'un segment de réponse est prêt, sans attendre la réponse complète
        │
        ▼
Retour audio vers Twilio Media Stream → l'appelant entend la réponse
```

### Gestion des Interruptions (Barge-In) — Clé du Réalisme
- Le serveur écoute en continu le flux audio entrant, même pendant que l'agent parle
- Si l'appelant recommence à parler pendant que le TTS diffuse encore une réponse,
  **couper immédiatement la lecture audio** et repasser en écoute — sinon l'expérience
  paraît robotique et frustrante (l'agent qui continue de parler par-dessus l'appelant)
- Implémentation : détection d'activité vocale (VAD) sur le flux entrant en parallèle
  du TTS sortant, avec un signal d'interruption qui vide le buffer audio en cours d'envoi

### Petites Relances Naturelles (Réduire la Latence Perçue)
- Le temps d'exécution d'un outil (ex: vérifier une disponibilité en base) peut prendre
  1-2 secondes — plutôt que de laisser un silence, l'agent peut dire une relance courte
  ("Un instant, je vérifie...") générée/déclenchée **avant** l'appel d'outil si celui-ci
  dépasse un seuil de latence attendu
- Cache/prompt caching sur le system prompt et les définitions d'outils (répétés à
  chaque tour) pour réduire la latence Claude

---

## 🛠️ Function Calling par Cas d'Usage

### Prise de Rendez-vous
```python
tools = [
    "check_availability(date, plage_horaire)",   # consulte le calendrier
    "book_appointment(date, heure, nom, motif)",  # crée le RDV
    "modify_appointment(id_rdv, nouvelle_date)",
    "cancel_appointment(id_rdv)",
    "escalate_to_human(raison)",
]
```

### Support Client / SAV
```python
tools = [
    "search_knowledge_base(question)",   # RAG sur la base de connaissances (cf Projet 1)
    "create_support_ticket(resume, priorite)",
    "check_order_status(numero_commande)",  # si applicable au cas de démo choisi
    "escalate_to_human(raison)",
]
```

Les deux jeux d'outils partagent le même moteur conversationnel — c'est l'intention
détectée en début d'appel (ou un menu vocal simple "Pour un rendez-vous, dites 1...")
qui oriente vers le bon contexte d'outils disponibles.

---

## 🗄️ Schéma de Données

```sql
CREATE TABLE appointments (
  id SERIAL PRIMARY KEY,
  caller_phone VARCHAR(20),
  caller_name VARCHAR(200),
  scheduled_at TIMESTAMP NOT NULL,
  motif TEXT,
  status VARCHAR(20) DEFAULT 'confirmed', -- confirmed | cancelled | modified
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE support_tickets (
  id SERIAL PRIMARY KEY,
  caller_phone VARCHAR(20),
  summary TEXT,
  priority VARCHAR(10), -- low | medium | high
  status VARCHAR(20) DEFAULT 'open',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE call_logs (
  id SERIAL PRIMARY KEY,
  twilio_call_sid VARCHAR(100) UNIQUE,
  use_case VARCHAR(20), -- rdv | support
  transcript TEXT,       -- transcript complet (avec consentement, cf contraintes)
  duration_seconds INTEGER,
  outcome VARCHAR(50),    -- booked | cancelled | escalated | resolved | abandoned
  escalated_to_human BOOLEAN DEFAULT false,
  avg_turn_latency_ms INTEGER,
  tool_calls_count INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 📈 Observabilité (Aligné avec la Checklist Production-Ready)

- Logger chaque appel : durée, nombre de tours de parole, outils appelés, résultat final
  (RDV pris/annulé/échoué, ticket créé, escalade), latence moyenne par tour
- Alerting si le taux d'escalade dépasse un seuil anormal (signal que l'agent galère sur
  certains types de demandes) ou si la latence moyenne dérive
- Dashboard admin : liste des appels récents avec transcript, RDV du jour, tickets ouverts

---

## 🧪 Tests

- **Tests unitaires** : parsing des créneaux horaires demandés en langage naturel,
  validation des arguments d'outils avant exécution
- **Tests d'intégration pipeline** : simuler un appel de bout en bout avec un fichier
  audio pré-enregistré en entrée, vérifier que le bon outil est appelé avec les bons
  arguments
- **Benchmark de latence** : mesurer la latence moyenne et P95 par tour de parole
  (objectif : < 1.2s du silence de l'appelant à la première syllabe de la réponse)
- **Scénarios de test conversationnels** : dataset de 15-20 scénarios types (RDV simple,
  RDV avec créneaux indisponibles nécessitant une négociation, demande hors-sujet,
  demande d'escalade explicite, interruption en plein milieu de la réponse de l'agent)
  à rejouer pour valider le comportement avant chaque déploiement

---

## 🚀 Roadmap de Développement

### Phase 1 — Fondations Téléphonie (semaine 1)
- [ ] Setup Twilio (numéro, Media Streams), serveur FastAPI + WebSocket minimal
- [ ] Pipeline STT → écho simple (renvoyer ce que l'appelant a dit, en texte, pour valider la chaîne audio)
- [ ] Intégration Deepgram streaming

### Phase 2 — Boucle Conversationnelle (semaine 2)
- [ ] Intégration Claude avec tool_use, premiers outils RDV
- [ ] Intégration TTS streaming, premier aller-retour vocal complet
- [ ] Gestion du barge-in (interruption)

### Phase 3 — Les Deux Cas d'Usage (semaine 3)
- [ ] Outils complets RDV (check/book/modify/cancel)
- [ ] Intégration RAG support (réutilisation architecture Projet 1)
- [ ] Menu d'orientation début d'appel (RDV vs support)
- [ ] Escalade vers un humain (transfert Twilio)

### Phase 4 — Réalisme & Fiabilité (semaine 4)
- [ ] Relances naturelles pendant les appels d'outils longs
- [ ] Confirmations orales avant actions engageantes
- [ ] Prompt caching, optimisation latence globale
- [ ] Scénarios de test rejoués + benchmark latence

### Phase 5 — Dashboard & Observabilité (semaine 5)
- [ ] Dashboard admin Next.js (appels, RDV, tickets, transcripts)
- [ ] Logging complet + alerting basique
- [ ] Documentation transparence/consentement affichée publiquement

---

## 📝 README à Produire

- **Décisions d'architecture** : pourquoi pipeline modulaire plutôt que speech-to-speech
  natif, comment la latence a été optimisée étage par étage (chiffres avant/après)
- **Limites connues** : accents/bruit de fond dégradant la reconnaissance vocale,
  gestion imparfaite des phrases très longues ou des sujets hors-scope, dépendance à la
  qualité réseau de l'appelant
- **Métriques** : latence moyenne/P95 par tour, taux de résolution sans escalade,
  taux de succès sur le dataset de scénarios de test

---

## 🔑 Variables d'Environnement

```
ANTHROPIC_API_KEY=sk-ant-...
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=...
DEEPGRAM_API_KEY=...
ELEVENLABS_API_KEY=...            # ou CARTESIA_API_KEY selon le choix TTS
DATABASE_URL=postgresql://...     # Supabase
```

---

## ✅ Critères de Succès

- Appel de bout en bout fonctionnel sur les deux cas d'usage (RDV + support)
- Latence moyenne par tour < 1.2s, P95 < 2s
- Barge-in fonctionnel (interruption coupe bien la réponse en cours)
- Taux de succès > 80% sur le dataset de scénarios de test rejoués
- Démo live crédible : "appelez ce numéro" fonctionne réellement devant un recruteur
- Transparence IA + consentement enregistrement énoncés clairement en début d'appel
