-- Sentri Analytics Pipeline — Aurora PostgreSQL schema
-- Run once after Aurora cluster is provisioned.
-- All inserts use ON CONFLICT DO NOTHING for idempotency.

CREATE TABLE IF NOT EXISTS devices (
    device_id     TEXT PRIMARY KEY,           -- RPi hardware serial
    dock_name     TEXT,                        -- human-readable label from host_config.json
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    run_id           UUID PRIMARY KEY,          -- deterministic UUID v5(device_id + run_timestamp)
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
    device_id     TEXT NOT NULL,               -- denormalized for query convenience
    protocol      TEXT NOT NULL,               -- denormalized for query convenience
    well          SMALLINT NOT NULL,           -- 1–4
    channel       TEXT NOT NULL,               -- 'fam' | 'rox'
    call          TEXT NOT NULL,               -- 'Detected' | 'Not Detected' | 'Inconclusive' | 'ROX Unavailable'
    cq            NUMERIC(6,2),                -- null when call != 'Detected'
    run_timestamp TIMESTAMPTZ NOT NULL,        -- denormalized, indexed
    UNIQUE (run_id, well, channel)
);
CREATE INDEX IF NOT EXISTS run_results_run_timestamp_idx ON run_results (run_timestamp);
CREATE INDEX IF NOT EXISTS run_results_protocol_idx      ON run_results (protocol);

-- Primary analytics query: inconclusive rate by protocol
-- SELECT
--     r.protocol,
--     COUNT(*) FILTER (WHERE rr.call = 'Inconclusive')                    AS inconclusive_count,
--     COUNT(*) FILTER (WHERE rr.call != 'ROX Unavailable')               AS eligible_count,
--     ROUND(
--         COUNT(*) FILTER (WHERE rr.call = 'Inconclusive')::numeric /
--         NULLIF(COUNT(*) FILTER (WHERE rr.call != 'ROX Unavailable'), 0),
--     4) AS inconclusive_rate
-- FROM run_results rr
-- JOIN runs r USING (run_id)
-- WHERE r.aborted = false
-- GROUP BY r.protocol
-- ORDER BY inconclusive_rate DESC;
