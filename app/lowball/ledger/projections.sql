-- Derived state.  Every table here is dropped and rebuilt by replaying the
-- event log, so nothing may be written to these tables except by a projection
-- handler.  If a figure cannot be reconstructed from events, it does not
-- belong in this file.

DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS offers;
DROP TABLE IF EXISTS items;
DROP TABLE IF EXISTS listings;   -- removed with auction house tracking
DROP TABLE IF EXISTS exits;
DROP TABLE IF EXISTS rule_firings;
DROP TABLE IF EXISTS valuations;

-- One negotiation over one item: an ordered chain of offers (Part 8).
CREATE TABLE sessions (
    session_id   TEXT PRIMARY KEY,
    tag          TEXT,
    display_name TEXT,
    rarity       TEXT,
    signature    TEXT,                    -- JSON ItemSignature
    uid          TEXT,
    counterparty TEXT,
    started_ts   TEXT,
    ended_ts     TEXT,
    state        TEXT,                    -- ACTIVE | CONFIRMED | ABANDONED
    item_id      TEXT,                    -- set once the item is acquired
    offer_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE offers (
    offer_id       TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    tag            TEXT NOT NULL,
    signature      TEXT,
    est_value      INTEGER,
    confidence     REAL,
    offer_pct      REAL,                  -- fraction below estimate, 0.10 = -10%
    offer_coins    INTEGER,
    outcome        TEXT,                  -- PENDING|CONFIRMED|REJECTED|COUNTERED|ABANDONED
    counter_price  INTEGER,
    settled_price  INTEGER,               -- what was actually paid, if confirmed
    is_exploration INTEGER NOT NULL DEFAULT 0,
    counterparty   TEXT,
    ts             TEXT
);

CREATE INDEX idx_offers_session ON offers(session_id, seq);
CREATE INDEX idx_offers_tag     ON offers(tag, outcome);

CREATE TABLE items (
    item_id          TEXT PRIMARY KEY,
    uid              TEXT,                -- SkyBlock item uuid, when it has one
    tag              TEXT NOT NULL,
    display_name     TEXT,
    rarity           TEXT,
    category         TEXT,
    signature        TEXT,                -- JSON ItemSignature
    acquired_ts      TEXT,
    cost_basis       INTEGER,
    state            TEXT,                -- HELD | SOLD | KEPT
    est_value_now    INTEGER,
    est_value_ts     TEXT,
    counterparty     TEXT,
    session_id       TEXT,
    exit_ts          TEXT
);

CREATE INDEX idx_items_state ON items(state);
CREATE INDEX idx_items_uid   ON items(uid);
CREATE INDEX idx_items_tag   ON items(tag);

CREATE TABLE exits (
    exit_id        TEXT PRIMARY KEY,
    item_id        TEXT NOT NULL,
    route          TEXT NOT NULL,         -- SOLD | KEPT
    ts             TEXT,
    gross          INTEGER,
    fees_total     INTEGER,               -- claim tax, when the sale was taxed
    net            INTEGER,               -- gross - fees_total
    cost_basis     INTEGER,
    profit         INTEGER,               -- net - cost_basis
    hold_seconds   INTEGER,
    counterparty   TEXT,                  -- who bought it, when that is known
    taxed          INTEGER NOT NULL DEFAULT 0,
    note           TEXT
);

CREATE INDEX idx_exits_item  ON exits(item_id);
CREATE INDEX idx_exits_route ON exits(route, ts);

-- Which rules fired on which offer.  Read back to badge the number in the UI.
CREATE TABLE rule_firings (
    offer_id   TEXT NOT NULL,
    rule_name  TEXT NOT NULL,
    detail     TEXT,
    PRIMARY KEY (offer_id, rule_name)
);

-- Every valuation ever recorded, so held items can be marked to market over
-- time and the estimate at purchase can be compared with what was realised.
CREATE TABLE valuations (
    valuation_id TEXT PRIMARY KEY,
    item_id      TEXT,
    session_id   TEXT,
    tag          TEXT NOT NULL,
    signature    TEXT,
    estimate     INTEGER,
    confidence   REAL,
    lbin         INTEGER,
    median       INTEGER,
    sell_seconds INTEGER,
    ts           TEXT
);

CREATE INDEX idx_valuations_item ON valuations(item_id, ts);
CREATE INDEX idx_valuations_tag  ON valuations(tag, ts);
