-- Schema del progetto "Etna volcanic data".
-- Esegui con: psql -U <user> -d etna_data -f db/schema.sql

CREATE TABLE IF NOT EXISTS terremoti (
    id                  SERIAL PRIMARY KEY,
    event_id            TEXT UNIQUE NOT NULL,   -- id evento assegnato dalla fonte
    event_time          TIMESTAMPTZ NOT NULL,
    latitude            DOUBLE PRECISION NOT NULL,
    longitude           DOUBLE PRECISION NOT NULL,
    depth_km            DOUBLE PRECISION,
    magnitude           DOUBLE PRECISION,
    mag_type            TEXT,
    author              TEXT,
    catalog             TEXT,
    event_location_name TEXT,
    source              TEXT NOT NULL,          -- es. 'ISIDe_FDSN', 'EtnaRCSC'
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_terremoti_time ON terremoti (event_time);

CREATE TABLE IF NOT EXISTS hotspot (
    id           SERIAL PRIMARY KEY,
    latitude     DOUBLE PRECISION NOT NULL,
    longitude    DOUBLE PRECISION NOT NULL,
    acq_date     DATE NOT NULL,
    acq_time     TEXT NOT NULL,       -- orario UTC come stringa (es. "1210")
    satellite    TEXT,
    instrument   TEXT,
    confidence   TEXT,
    frp          DOUBLE PRECISION,    -- Fire Radiative Power (MW)
    daynight     TEXT,
    source       TEXT NOT NULL DEFAULT 'NASA_FIRMS',
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (latitude, longitude, acq_date, acq_time, satellite)
);
CREATE INDEX IF NOT EXISTS idx_hotspot_date ON hotspot (acq_date);

-- Popolata manualmente (vedi data_seed/eventi_noti_template.csv) a partire
-- dallo storico eruttivo del Global Volcanism Program (Smithsonian).
CREATE TABLE IF NOT EXISTS eventi_noti (
    id           SERIAL PRIMARY KEY,
    event_date   DATE NOT NULL,
    event_type   TEXT NOT NULL,   -- es. 'eruzione_sommitale', 'eruzione_laterale', 'cambio_livello_allerta'
    description  TEXT,
    source       TEXT NOT NULL DEFAULT 'GVP_Smithsonian'
);
-- Rende idempotente load_eventi_noti (indice e non vincolo inline, così si applica anche a DB già creati).
CREATE UNIQUE INDEX IF NOT EXISTS uq_eventi_noti ON eventi_noti (event_date, event_type, source);

-- Placeholder per il tremore vulcanico (fase successiva: pipeline ObsPy su dataselect).
CREATE TABLE IF NOT EXISTS tremore (
    id           SERIAL PRIMARY KEY,
    station      TEXT NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    window_end   TIMESTAMPTZ NOT NULL,
    rms_value    DOUBLE PRECISION NOT NULL,
    band_hz      TEXT NOT NULL DEFAULT '0.5-2.5',
    source       TEXT NOT NULL DEFAULT 'INGV_FDSN_dataselect',
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (station, window_start, band_hz)
);
