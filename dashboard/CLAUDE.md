# Dashboard Admin — Allo-IA

Consultation seule (Next.js, App Router) : appels récents + transcripts,
rendez-vous à venir, tickets ouverts, alertes basiques, et la page de
transparence/consentement publique (cf `../CLAUDE.md` à la racine du projet).

Consomme l'API en lecture seule exposée par le serveur temps réel
(`../server/app/api/admin.py`) via `lib/api.ts`. Variables d'environnement :
`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_ADMIN_KEY` (cf `.env.example`).
