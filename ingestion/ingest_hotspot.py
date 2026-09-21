"""
Ingestion hotspot termici — NASA FIRMS Area API.

Fonte VERIFICATA: struttura URL e parametri confermati dalla documentazione
ufficiale (https://firms.modaps.eosdis.nasa.gov/api/area/) ed esempi pubblici.

URL: https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{AREA}/{DAY_RANGE}/{DATE}
- SOURCE: usiamo le versioni "_SP" (Standard Processing, dati storici validati)
  invece di "_NRT" (Near Real Time, solo ultimi ~2 mesi).
- DAY_RANGE: 5 è il massimo accettato oggi da FIRMS (con 10 risponde 400
  "Invalid day range. Expects [1..5]"); se in futuro alza il limite, aumentalo qui.
- DATE: data di partenza del range di DAY_RANGE giorni.

NOTA IMPORTANTE PRIMA DEL BACKFILL COMPLETO:
la direzione esatta del parametro DATE (se il range parte da quella data in avanti
o all'indietro) va confermata con una singola chiamata di test — la documentazione
non lo specifica in modo inequivocabile. Lo script stampa il range di acq_date
effettivamente ricevuto ad ogni chunk: controlla il primo output prima di lanciare
il backfill su anni interi.

Esecuzione:
    python -m ingestion.ingest_hotspot --from-date 2012-01-19 --to-date 2012-01-31
"""
import argparse
import io
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from config import FIRMS_AREA_STRING, FIRMS_MAP_KEY
from db.connection import get_connection

BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
DAY_RANGE = 5

# instrument -> (source_id_FIRMS, data disponibile da)
SOURCES = {
    "MODIS": "MODIS_SP",
    "VIIRS": "VIIRS_SNPP_SP",
}

UPSERT_SQL = """
    INSERT INTO hotspot (
        latitude, longitude, acq_date, acq_time,
        satellite, instrument, confidence, frp, daynight, source
    ) VALUES (
        %(latitude)s, %(longitude)s, %(acq_date)s, %(acq_time)s,
        %(satellite)s, %(instrument)s, %(confidence)s, %(frp)s, %(daynight)s,
        'NASA_FIRMS'
    )
    ON CONFLICT (latitude, longitude, acq_date, acq_time, satellite) DO NOTHING;
"""


DB_COLUMNS = [
    "latitude", "longitude", "acq_date", "acq_time",
    "satellite", "instrument", "confidence", "frp", "daynight",
]


def _mask_key(text: str) -> str:
    """Nasconde la MAP_KEY: l'URL FIRMS la contiene e finirebbe nei messaggi d'errore."""
    return text.replace(FIRMS_MAP_KEY, "***") if FIRMS_MAP_KEY else text


def normalize_hotspot_df(csv_text: str, instrument: str) -> pd.DataFrame:
    """Converte il CSV FIRMS in un DataFrame pronto per l'insert (vuoto se non ci sono righe)."""
    if not csv_text.strip():
        return pd.DataFrame(columns=DB_COLUMNS)
    # acq_time va letto come stringa: "0035" come intero diventerebbe 35.
    # confidence è numerica per MODIS e una lettera (l/n/h) per VIIRS.
    df = pd.read_csv(io.StringIO(csv_text), dtype={"acq_time": str, "confidence": str})
    missing = [c for c in DB_COLUMNS if c != "instrument" and c not in df.columns]
    if missing:
        # FIRMS risponde 200 con un testo d'errore (es. MAP_KEY non valida) invece di un CSV.
        raise ValueError(f"risposta FIRMS inattesa, colonne mancanti {missing}: {csv_text[:100]!r}")
    df["instrument"] = instrument
    df["acq_time"] = df["acq_time"].str.zfill(4)
    df = df[DB_COLUMNS]
    # NaN -> None, altrimenti psycopg2 inserirebbe 'NaN' anche nelle colonne testuali.
    return df.astype(object).where(df.notna(), None)


def fetch_chunk(instrument: str, chunk_start: date) -> pd.DataFrame:
    source = SOURCES[instrument]
    url = f"{BASE_URL}/{FIRMS_MAP_KEY}/{source}/{FIRMS_AREA_STRING}/{DAY_RANGE}/{chunk_start.isoformat()}"
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(_mask_key(str(exc))) from None
    try:
        return normalize_hotspot_df(resp.text, instrument)
    except ValueError as exc:
        raise ValueError(_mask_key(str(exc))) from None


def upsert_rows(conn, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    records = df.to_dict("records")
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, records)
    conn.commit()
    return len(records)


def run(from_date: date, to_date: date, pause_seconds: float = 2.0) -> None:
    if not FIRMS_MAP_KEY:
        raise SystemExit("FIRMS_MAP_KEY mancante: impostala nel file .env")

    conn = get_connection()
    total = 0
    try:
        for instrument in SOURCES:
            chunk_start = from_date
            while chunk_start <= to_date:
                print(f"[{instrument}] chunk da {chunk_start} ({DAY_RANGE} giorni) ...")
                try:
                    df = fetch_chunk(instrument, chunk_start)
                except Exception as exc:  # errori di rete o CSV vuoto/malformato
                    print(f"  [ERRORE] {exc}")
                    chunk_start += timedelta(days=DAY_RANGE)
                    time.sleep(pause_seconds)
                    continue

                if not df.empty:
                    print(f"  range acq_date ricevuto: {df['acq_date'].min()} -> {df['acq_date'].max()}"
                          f"  ({len(df)} righe)")
                n = upsert_rows(conn, df)
                total += n
                chunk_start += timedelta(days=DAY_RANGE)
                time.sleep(pause_seconds)
    finally:
        conn.close()
    print(f"\nCompletato. Totale righe salvate/aggiornate: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingestion hotspot NASA FIRMS area Etna")
    parser.add_argument("--from-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                         default=date(2012, 1, 19), help="MODIS SP parte dal 2000, VIIRS SNPP dal 2012-01-19")
    parser.add_argument("--to-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                         default=date.today())
    args = parser.parse_args()
    run(args.from_date, args.to_date)
