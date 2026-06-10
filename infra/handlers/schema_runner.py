import os
import psycopg

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,
    dock_name     TEXT,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    run_id           UUID PRIMARY KEY,
    device_id        TEXT NOT NULL REFERENCES devices(device_id),
    protocol         TEXT NOT NULL,
    run_name         TEXT,
    run_timestamp    TIMESTAMPTZ NOT NULL,
    duration_seconds INTEGER,
    aborted          BOOLEAN NOT NULL DEFAULT false,
    received_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS runs_run_timestamp_idx ON runs (run_timestamp);
CREATE INDEX IF NOT EXISTS runs_protocol_idx       ON runs (protocol);

CREATE TABLE IF NOT EXISTS run_results (
    result_id     BIGSERIAL PRIMARY KEY,
    run_id        UUID NOT NULL REFERENCES runs(run_id),
    device_id     TEXT NOT NULL,
    protocol      TEXT NOT NULL,
    well          SMALLINT NOT NULL,
    channel       TEXT NOT NULL,
    call          TEXT NOT NULL,
    cq            NUMERIC(6,2),
    run_timestamp TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, well, channel)
);
CREATE INDEX IF NOT EXISTS run_results_run_timestamp_idx ON run_results (run_timestamp);
CREATE INDEX IF NOT EXISTS run_results_protocol_idx      ON run_results (protocol);
"""


def handler(event, context):
    dsn = os.environ["DB_DSN"]
    # DB_DSN points to /sentri — connect to /postgres first to create the database
    bootstrap_dsn = dsn.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(bootstrap_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = 'sentri'")
            if not cur.fetchone():
                cur.execute("CREATE DATABASE sentri")
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        conn.commit()
    return {"status": "schema applied"}
