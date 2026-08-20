-- CineFlow AI — ClickHouse schema
-- Applied via ClickHouseService.run_migrations() / scripts/init_clickhouse.py

CREATE TABLE IF NOT EXISTS projects (
    project_id      String,
    title           String,
    genre           String,
    input_mode      String,       -- 'idea' | 'screenplay'
    already_funded  UInt8,
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, created_at);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id          String,
    project_id      String,
    agent_name      String,
    status          String,       -- pending|running|completed|failed|retrying|skipped
    started_at      DateTime,
    completed_at    Nullable(DateTime),
    duration_ms     UInt32,
    input_summary   String,
    output_summary  String,
    error           String,
    retry_count     UInt8
) ENGINE = MergeTree()
ORDER BY (project_id, started_at);

CREATE TABLE IF NOT EXISTS agent_outputs (
    project_id      String,
    agent_name      String,
    output_json     String,       -- full structured output, stored as JSON text
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, created_at);

CREATE TABLE IF NOT EXISTS budget_breakdowns (
    project_id      String,
    category        String,       -- cast, crew, equipment, vfx, marketing, contingency, ...
    amount          Float64,
    currency        String,
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, category);

CREATE TABLE IF NOT EXISTS producer_matches (
    project_id      String,
    producer_id     String,
    compatibility_pct Float32,
    genre_score     Float32,
    budget_score    Float32,
    geo_score       Float32,
    language_score  Float32,
    portfolio_score Float32,
    risk_score      Float32,
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, compatibility_pct);

CREATE TABLE IF NOT EXISTS production_schedule (
    project_id      String,
    stage           String,       -- development, pre-production, casting, ...
    start_date      Date,
    end_date        Date,
    depends_on      String,       -- comma-separated stage names
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, start_date);

CREATE TABLE IF NOT EXISTS risks (
    project_id      String,
    risk_type       String,       -- budget, scheduling, location, weather, ...
    probability_pct Float32,
    impact          String,       -- low|medium|high
    risk_score      Float32,
    explanation     String,
    mitigation      String,
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, risk_score);

CREATE TABLE IF NOT EXISTS investment_events (
    project_id      String,
    producer_id     String,
    event_type      String,       -- interested, info_request, meeting_request, offer_submitted
    amount          Nullable(Float64),
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, created_at);

CREATE TABLE IF NOT EXISTS workflow_metrics (
    project_id      String,
    total_duration_ms UInt32,
    agents_run      UInt8,
    agents_failed   UInt8,
    agents_retried  UInt8,
    created_at      DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (project_id, created_at);
