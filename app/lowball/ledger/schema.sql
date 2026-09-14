-- Durable storage.  Nothing in this file is ever rebuilt from anything else.
--
-- The events table is append-only.  There is no UPDATE and no DELETE against
-- it anywhere in the codebase; a mistake is fixed by appending a
-- MANUAL_CORRECTION that targets the offending event, so history stays intact
-- and the correction itself is auditable.

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    type         TEXT NOT NULL,
    session_id   TEXT,
    item_id      TEXT,
    payload      TEXT NOT NULL            -- JSON object
);

CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_item    ON events(item_id);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(type, ts);

-- Cached API responses, keyed on (tag, filter signature).  Durable across
-- restarts so a relaunch mid-session does not re-spend the rate limit.
CREATE TABLE IF NOT EXISTS api_cache (
    key         TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    fetched_ts  TEXT NOT NULL,
    ttl_s       INTEGER NOT NULL,
    source      TEXT
);

CREATE INDEX IF NOT EXISTS idx_api_cache_fetched ON api_cache(fetched_ts);

-- Auction house tracking was removed: an item's outcome is now recorded by
-- hand in the ledger, which made the scraper and its local sale history
-- redundant.  Dropped here so an older database stops carrying it.
DROP TABLE IF EXISTS ended_auctions;

-- Bookkeeping for incremental projection.
CREATE TABLE IF NOT EXISTS projection_state (
    name          TEXT PRIMARY KEY,
    last_event_id INTEGER NOT NULL DEFAULT 0
);

-- Wall-clock spans of active lowballing, used for the coins/hour figure in the
-- statistics tab.  Recorded by the app, not derived from trades.
CREATE TABLE IF NOT EXISTS work_sessions (
    id         INTEGER PRIMARY KEY,
    started_ts TEXT NOT NULL,
    ended_ts   TEXT
);
