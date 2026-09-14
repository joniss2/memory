-- 0001_initial: das vollständige Schema aus dem Architekturentwurf, Abschnitt 4.
--
-- Sieben Tabellen tragen das Datenmodell: turns, facts, lineage, entities,
-- edges, traces, trace_steps. Eine achte -- erasure_receipts -- hält den
-- Löschbeleg aus Abschnitt 7, Schritt 6.
--
-- ${EMBEDDING_DIM} wird vom Migrationsrunner ersetzt (Vorgabe 1024).

-- Verlangt pgvector >= 0.5.0: davor gibt es keinen HNSW-Index. Das Image
-- pgvector/pgvector:pg16 erfüllt das; ein selbst gebautes Postgres nicht
-- zwangsläufig.
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------- 4.1 Rohmaterial

CREATE TABLE turns (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,        -- die Person, um die es geht
  session_id  TEXT NOT NULL,
  role        TEXT NOT NULL,        -- user | assistant
  content     TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Rohmaterial ist die unmittelbarste personenbezogene Ablage. Bei einer
  -- Löschung wird content geleert, die Zeile bleibt als Beleg stehen.
  redacted_at TIMESTAMPTZ,
  CONSTRAINT turns_role_check CHECK (role IN ('user', 'assistant', 'system'))
);
CREATE INDEX turns_subject_time_idx ON turns (subject_id, occurred_at);
CREATE INDEX turns_session_idx ON turns (subject_id, session_id, occurred_at);

-- ---------------------------------------------------------------- 4.2 Fakten, bitemporal

CREATE TYPE fact_status AS ENUM ('active', 'superseded', 'retracted', 'erased');

CREATE TABLE facts (
  id            BIGSERIAL PRIMARY KEY,
  subject_id    TEXT NOT NULL,
  content       TEXT NOT NULL,
  embedding     VECTOR(${EMBEDDING_DIM}),
  content_tsv   TSVECTOR,
  status        fact_status NOT NULL DEFAULT 'active',

  -- Gültigkeitszeit: seit wann gilt das in der Welt?
  valid_from    TIMESTAMPTZ NOT NULL,
  valid_to      TIMESTAMPTZ,

  -- Transaktionszeit: seit wann weiß das System davon?
  recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  invalidated_at TIMESTAMPTZ,

  confidence    REAL,
  origin_turn   BIGINT REFERENCES turns(id),

  -- Strukturierte Projektion des Fakts, sofern die Extraktion eine geliefert
  -- hat. Speist entities/edges und erlaubt der Konsolidierung einen
  -- Prädikatsvergleich statt reiner Textähnlichkeit.
  triple        JSONB,
  erased_at     TIMESTAMPTZ,

  CONSTRAINT facts_valid_range_check CHECK (valid_to IS NULL OR valid_to >= valid_from),
  CONSTRAINT facts_confidence_check CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1))
);

CREATE INDEX facts_embedding_idx ON facts USING hnsw (embedding vector_cosine_ops);
CREATE INDEX facts_subject_status_idx ON facts (subject_id, status);
CREATE INDEX facts_tsv_idx ON facts USING gin (content_tsv);
CREATE INDEX facts_origin_turn_idx ON facts (origin_turn);
-- Transaktionszeit-Fenster für Replay ("was wusste das System am 14. Mai?")
CREATE INDEX facts_txtime_idx ON facts (subject_id, recorded_at, invalidated_at);

-- ---------------------------------------------------------------- 4.5 Traces
-- Vor lineage angelegt: lineage.trace_id referenziert traces.

CREATE TYPE trace_kind AS ENUM ('write', 'read');

CREATE TABLE traces (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,
  kind        trace_kind NOT NULL,
  turn_id     BIGINT REFERENCES turns(id),
  query       TEXT,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  duration_ms INTEGER
);
CREATE INDEX traces_subject_time_idx ON traces (subject_id, started_at DESC);
CREATE INDEX traces_turn_idx ON traces (turn_id);

CREATE TABLE trace_steps (
  id          BIGSERIAL PRIMARY KEY,
  trace_id    BIGINT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
  stage       SMALLINT NOT NULL,     -- 1..4
  model       TEXT,
  prompt_ref  TEXT,                  -- Version des Prompt-Templates
  input       JSONB,
  output      JSONB,
  duration_ms INTEGER,
  tokens_in   INTEGER,
  tokens_out  INTEGER,
  -- Nach einer Löschung schemakonform geschwärzt; Struktur und Zeitstempel
  -- bleiben, die Werte gehen.
  redacted_at TIMESTAMPTZ,
  CONSTRAINT trace_steps_stage_check CHECK (stage BETWEEN 1 AND 4)
);
CREATE INDEX trace_steps_trace_idx ON trace_steps (trace_id, stage);

-- ---------------------------------------------------------------- 4.3 Abstammung

CREATE TYPE decision AS ENUM ('add', 'update', 'retract', 'noop', 'merge');

CREATE TABLE lineage (
  id           BIGSERIAL PRIMARY KEY,
  fact_id      BIGINT NOT NULL REFERENCES facts(id),
  parent_id    BIGINT REFERENCES facts(id),   -- NULL bei 'add'
  op           decision NOT NULL,
  rationale    TEXT,                          -- Begründung des Modells
  trace_id     BIGINT NOT NULL REFERENCES traces(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Wenn die Richtlinie aus Abschnitt 5, Stufe 2 die Modellentscheidung
  -- überstimmt hat, steht hier die ursprünglich vorgeschlagene Entscheidung.
  proposed_op  decision,
  CONSTRAINT lineage_add_has_no_parent CHECK (op <> 'add' OR parent_id IS NULL),
  CONSTRAINT lineage_no_self_parent CHECK (parent_id IS NULL OR parent_id <> fact_id)
);
CREATE INDEX lineage_fact_idx ON lineage (fact_id);
CREATE INDEX lineage_parent_idx ON lineage (parent_id);
CREATE INDEX lineage_trace_idx ON lineage (trace_id);

-- ---------------------------------------------------------------- 4.4 Graph

CREATE TABLE entities (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,
  name        TEXT NOT NULL,
  kind        TEXT,                  -- person | ort | organisation | ...
  embedding   VECTOR(${EMBEDDING_DIM}),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- NULLS NOT DISTINCT: ohne das wäre kind IS NULL beliebig oft eintragbar
  -- und die Deduplizierung liefe leer.
  UNIQUE NULLS NOT DISTINCT (subject_id, name, kind)
);
CREATE INDEX entities_embedding_idx ON entities USING hnsw (embedding vector_cosine_ops);
CREATE INDEX entities_subject_name_idx ON entities (subject_id, lower(name));

CREATE TABLE edges (
  id          BIGSERIAL PRIMARY KEY,
  subject_id  TEXT NOT NULL,
  src         BIGINT NOT NULL REFERENCES entities(id),
  predicate   TEXT NOT NULL,
  dst         BIGINT NOT NULL REFERENCES entities(id),
  fact_id     BIGINT NOT NULL REFERENCES facts(id),   -- jede Kante hat einen Beleg
  valid_from  TIMESTAMPTZ NOT NULL,
  valid_to    TIMESTAMPTZ
);
CREATE INDEX edges_src_open_idx ON edges (src) WHERE valid_to IS NULL;
CREATE INDEX edges_dst_open_idx ON edges (dst) WHERE valid_to IS NULL;
CREATE INDEX edges_fact_idx ON edges (fact_id);
CREATE INDEX edges_subject_idx ON edges (subject_id);

-- ---------------------------------------------------------------- 7 Löschbeleg

CREATE TABLE erasure_receipts (
  id            BIGSERIAL PRIMARY KEY,
  subject_id    TEXT NOT NULL,
  scope         TEXT NOT NULL,        -- subject | facts
  requested_by  TEXT,
  reason        TEXT,
  -- Was tatsächlich weggegangen ist: Fakt-, Kanten-, Trace-Schritt- und
  -- Turn-Kennungen plus die Wurzeln, von denen die Hülle ausging.
  affected      JSONB NOT NULL,
  executed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX erasure_receipts_subject_idx ON erasure_receipts (subject_id, executed_at DESC);
