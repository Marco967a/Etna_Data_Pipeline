"""
Ingestion terremoti — catalogo ISIDe (INGV), via servizio standard fdsnws-event.

Fonte VERIFICATA: endpoint e formato di output confermati dalla documentazione
ufficiale INGV (https://terremoti.ingv.it/webservices_and_software) e da esempi
pubblici del servizio (formato "text", pipe-separated).

Copertura storica: dal 1985 a oggi per l'area etnea (bounding box in config.py).

Esecuzione:
    python -m ingestion.ingest_terremoti
    python -m ingestion.ingest_terremoti --from-year 2018 --to-year 2024
"""
import argparse
import re
import time
from datetime import date

import requests

from config import ETNA_BBOX
from db.connection import get_connection

BASE_URL = "https://webservices.ingv.it/fdsnws/event/1/query"

# Colonne nell'ordine restituito dal formato "text" del servizio fdsnws-event INGV:
# #EventID|Time|Latitude|Longitude|Depth/Km|Author|Catalog|Contributor|
# ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType
COLUMNS = [
    "event_id", "event_time", "latitude", "longitude", "depth_km",
    "author", "catalog", "contributor", "contributor_id",
    "mag_type", "magnitude", "mag_author", "event_location_name", "event_type",
]

UPSERT_SQL = """
    INSERT INTO terremoti (
        event_id, event_time, latitude, longitude, depth_km,
        magnitude, mag_type, author, catalog, event_location_name, source
    ) VALUES (
        %(event_id)s, %(event_time)s, %(latitude)s, %(longitude)s, %(depth_km)s,
        %(magnitude)s, %(mag_type)s, %(author)s, %(catalog)s, %(event_location_name)s,
        'ISIDe_FDSN'
    )
    ON CONFLICT (event_id) DO UPDATE SET
        event_time = EXCLUDED.event_time,
        magnitude = EXCLUDED.magnitude,
        depth_km = EXCLUDED.depth_km,
        event_location_name = EXCLUDED.event_location_name;
"""


NUMERIC_COLUMNS = {"latitude", "longitude", "depth_km", "magnitude"}


def _clean(column: str, value: str):
    """Campo vuoto -> None; colonne numeriche -> float (una stringa vuota romperebbe l'insert)."""
    value = value.strip()
    if not value:
        return None
    return float(value) if column in NUMERIC_COLUMNS else value


def _as_utc(event_time: str) -> str:
    """
    Gli orari FDSN sono UTC ma il formato "text" non riporta il fuso: senza un offset
    esplicito PostgreSQL li interpreterebbe nel fuso della sessione (es. Europe/Berlin)
    sballando l'istante di 1-2 ore.
    """
    if re.search(r"(Z|[+-]\d{2}:?\d{2})$", event_time):
        return event_time
    return event_time + "+00:00"


def parse_text(text: str) -> list[dict]:
    """Parsa l'output "text" (pipe-separated) di fdsnws-event in una lista di dict."""
    rows = []
    for line in text.strip().splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) != len(COLUMNS):
            # Riga inattesa: la salto ma non blocco l'intero import.
            print(f"  [WARN] riga con {len(fields)} campi (attesi {len(COLUMNS)}), saltata")
            continue
        try:
            row = {col: _clean(col, val) for col, val in zip(COLUMNS, fields)}
        except ValueError:
            print(f"  [WARN] valore numerico non valido, riga saltata: {line[:80]}")
            continue
        row["event_time"] = _as_utc(row["event_time"])
        rows.append(row)
    return rows


def fetch_chunk(start: str, end: str) -> list[dict]:
    """Scarica e parsa un intervallo di terremoti (formato testo pipe-separated)."""
    params = {
        "starttime": start,
        "endtime": end,
        "minlatitude": ETNA_BBOX["min_lat"],
        "maxlatitude": ETNA_BBOX["max_lat"],
        "minlongitude": ETNA_BBOX["min_lon"],
        "maxlongitude": ETNA_BBOX["max_lon"],
        "format": "text",
    }
    resp = requests.get(BASE_URL, params=params, timeout=60)
    resp.raise_for_status()
    return parse_text(resp.text)


def upsert_rows(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    conn.commit()
    return len(rows)


def run(from_year: int, to_year: int, pause_seconds: float = 1.0) -> None:
    """Scarica anno per anno per evitare risposte troppo grandi in un'unica richiesta."""
    conn = get_connection()
    total = 0
    try:
        for year in range(from_year, to_year + 1):
            start = f"{year}-01-01T00:00:00"
            end = (
                f"{year}-12-31T23:59:59"
                if year < date.today().year
                else date.today().isoformat() + "T00:00:00"
            )
            print(f"[{year}] richiesta {start} -> {end} ...")
            try:
                rows = fetch_chunk(start, end)
            except requests.RequestException as exc:
                print(f"  [ERRORE] richiesta fallita per il {year}: {exc}")
                continue
            n = upsert_rows(conn, rows)
            total += n
            print(f"  {n} eventi salvati/aggiornati")
            time.sleep(pause_seconds)  # non martellare il servizio pubblico
    finally:
        conn.close()
    print(f"\nCompletato. Totale eventi processati: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingestion terremoti area Etna (ISIDe/FDSN)")
    parser.add_argument("--from-year", type=int, default=1999,
                         help="Anno di inizio (default 1999, coerente con EtnaRCSC)")
    parser.add_argument("--to-year", type=int, default=date.today().year)
    args = parser.parse_args()
    run(args.from_year, args.to_year)
