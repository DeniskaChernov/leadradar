CREATE TABLE IF NOT EXISTS gateway_origin (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    origin TEXT NOT NULL
);
