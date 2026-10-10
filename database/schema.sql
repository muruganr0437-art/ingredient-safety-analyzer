PRAGMA foreign_keys = ON;

-- Verified/curated scientific data lives in these tables ----------------------
CREATE TABLE IF NOT EXISTS ingredients (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_name      TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(trim(canonical_name)) > 0),
    ins_number          TEXT,
    e_number            TEXT,
    category            TEXT NOT NULL DEFAULT 'unspecified',
    purpose             TEXT NOT NULL DEFAULT '',
    hazard_summary      TEXT,
    evidence_level      TEXT NOT NULL DEFAULT 'not_assessed'
        CHECK (evidence_level IN ('established','limited','insufficient','not_assessed')),
    evidence_limitations TEXT,
    permitted_use_notes TEXT,
    allergen_notes      TEXT,
    precautions         TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_status IN ('unverified','reviewed','outdated')),
    reviewed_on         TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS synonyms (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    synonym       TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(synonym)) > 0),
    UNIQUE (ingredient_id, synonym)
);
CREATE INDEX IF NOT EXISTS idx_synonyms_synonym ON synonyms(synonym);

CREATE TABLE IF NOT EXISTS evidence_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id   INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    publisher       TEXT NOT NULL,
    url             TEXT NOT NULL CHECK (url LIKE 'http://%' OR url LIKE 'https://%'),
    publication_date TEXT,
    retrieval_date  TEXT,
    claim_supported TEXT NOT NULL,
    UNIQUE (ingredient_id, url, claim_supported)
);
CREATE INDEX IF NOT EXISTS idx_sources_ingredient ON evidence_sources(ingredient_id);

CREATE TABLE IF NOT EXISTS health_effects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id  INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    effect         TEXT NOT NULL,
    timeframe      TEXT NOT NULL DEFAULT 'other'
        CHECK (timeframe IN ('short_term','long_term','allergy_sensitivity','other')),
    body_system    TEXT,
    exposure_route TEXT NOT NULL DEFAULT 'oral',
    evidence_type  TEXT NOT NULL DEFAULT 'theoretical'
        CHECK (evidence_type IN ('established_causal','association','theoretical')),
    evidence_level TEXT NOT NULL DEFAULT 'insufficient'
        CHECK (evidence_level IN ('established','limited','insufficient','not_assessed')),
    conditions     TEXT,
    source_id      INTEGER REFERENCES evidence_sources(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_effects_ingredient ON health_effects(ingredient_id);

CREATE TABLE IF NOT EXISTS safety_limits (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ingredient_id       INTEGER NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    limit_type          TEXT NOT NULL DEFAULT 'ADI'
        CHECK (limit_type IN ('ADI','TDI','MTDI','other')),
    value_mg_per_kg_bw  REAL NOT NULL CHECK (value_mg_per_kg_bw > 0),
    expressed_as        TEXT,
    authority           TEXT NOT NULL,
    jurisdiction        TEXT NOT NULL DEFAULT 'International',
    source_id           INTEGER REFERENCES evidence_sources(id) ON DELETE SET NULL,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
        CHECK (verification_status IN ('unverified','reviewed','outdated')),
    reviewed_on         TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_limits_ingredient ON safety_limits(ingredient_id);

-- User session data (kept separate from curated science) ----------------------
CREATE TABLE IF NOT EXISTS analysis_sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    product_name TEXT,
    report_json  TEXT NOT NULL      -- redacted report (no images, no body weight)
);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON analysis_sessions(created_at);

CREATE TABLE IF NOT EXISTS analysis_findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
    input_name    TEXT NOT NULL,
    match_type    TEXT NOT NULL,
    confidence    REAL,
    risk_category TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_session ON analysis_findings(session_id);

-- AI-generated text is NEVER mixed with curated data -------------------------
CREATE TABLE IF NOT EXISTS ai_summaries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES analysis_sessions(id) ON DELETE CASCADE,
    model      TEXT,
    summary    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
