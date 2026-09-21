-- Schéma Allo-IA (PostgreSQL / Supabase) — cf CLAUDE.md
-- Appliquer avec : psql "$DATABASE_URL" -f app/db/schema.sql

CREATE TABLE IF NOT EXISTS appointments (
  id SERIAL PRIMARY KEY,
  caller_phone VARCHAR(20),
  caller_name VARCHAR(200),
  scheduled_at TIMESTAMP NOT NULL,
  motif TEXT,
  status VARCHAR(20) DEFAULT 'confirmed', -- confirmed | cancelled | modified
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_appointments_day
  ON appointments (scheduled_at) WHERE status = 'confirmed';

CREATE TABLE IF NOT EXISTS support_tickets (
  id SERIAL PRIMARY KEY,
  caller_phone VARCHAR(20),
  summary TEXT,
  priority VARCHAR(10), -- low | medium | high
  status VARCHAR(20) DEFAULT 'open',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS call_logs (
  id SERIAL PRIMARY KEY,
  twilio_call_sid VARCHAR(100) UNIQUE,
  use_case VARCHAR(20), -- rdv | support
  transcript TEXT,       -- transcript complet (avec consentement, cf CLAUDE.md)
  duration_seconds INTEGER,
  outcome VARCHAR(50),    -- booked | cancelled | escalated | resolved | abandoned
  escalated_to_human BOOLEAN DEFAULT false,
  avg_turn_latency_ms INTEGER,
  tool_calls_count INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Base de connaissances support : full-text search français.
-- (Le backend pgvector du Projet 1 peut remplacer cette table si le corpus
-- grossit — même interface côté application.)
CREATE TABLE IF NOT EXISTS knowledge_base (
  id SERIAL PRIMARY KEY,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('french', question || ' ' || answer)
  ) STORED
);
CREATE INDEX IF NOT EXISTS idx_kb_tsv ON knowledge_base USING gin (tsv);
