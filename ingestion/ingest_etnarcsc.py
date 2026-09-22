"""
Ingestion terremoti — EtnaRCSC (INGV Osservatorio Etneo), dal 1999.

Fonte VERIFICATA manualmente (nessun endpoint documentato pubblicamente): il form
(http://sismoweb.ct.ingv.it/Etna/catalogs/EtnaRCSC/catalogue.php) sottomette un
POST a earthquakes.php con i campi start/end date, filtri e opzioni di output.

Il pulsante "Make file" del sito è rotto lato server (risponde sempre 500 —
mysqli_sql_exception nello stack trace, bug del sito, non nostro): l'opzione
"Show table" invece funziona e restituisce una tabella HTML con tutti i risultati,
quindi la usiamo come export.

Colonne della tabella: DateTime|Magnitude|MagType|Depth(Km)|Latitude|Longitude|Region.
Il tr di ogni riga porta come id un UUID che usiamo come event_id (non collide con
gli id numerici di ISIDe/FDSN, quindi le due fonti coesistono nella stessa tabella
`terremoti`).

Fuso orario: confermato UTC incrociando l'evento ML4.9 del 2018-12-26 con ISIDe/FDSN
(vedi test_parsing.py) — stesso istante "2018-12-26 02:19:14" su entrambe le fonti
(differenza di magnitudo 4.8 vs 4.9 dovuta a revisioni successive del catalogo,
normale tra fonti diverse).

Esecuzione:
    python -m ingestion.ingest_etnarcsc
    python -m ingestion.ingest_etnarcsc --from-year 2018 --to-year 2024

Riferimento per la citazione (obbligatoria se usi questi dati):
Alparone, S. C. et al. (2020). Mt. Etna Revised and Concise Seismic Catalog from 1999
(EtnaRCSC) [Data set]. INGV. https://doi.org/10.13127/ETNASC/ETNARCSC
"""
import argparse
import html
import re
import time
from datetime import date

import requests

from db.connection import get_connection

BASE_URL = "http://sismoweb.ct.ingv.it/Etna/catalogs/EtnaRCSC/earthquakes.php"

ROW_RE = re.compile(r"<tr class='unselected' id='([0-9a-f-]+)'[^>]*>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td>(.*?)</td>", re.S)

# Ordine delle colonne <td> nella tabella "Show table" del sito.
COLUMNS = ["event_time", "magnitude", "mag_type", "depth_km", "latitude", "longitude", "region"]
NUMERIC_COLUMNS = {"magnitude", "depth_km", "latitude", "longitude"}

UPSERT_SQL = """
    INSERT INTO terremoti (
        event_id, event_time, latitude, longitude, depth_km,
        magnitude, mag_type, author, catalog, event_location_name, source
    ) VALUES (
        %(event_id)s, %(event_time)s, %(latitude)s, %(longitude)s, %(depth_km)s,
        %(magnitude)s, %(mag_type)s, 'INGV-OE', 'EtnaRCSC', %(region)s,
        'EtnaRCSC'
    )
    ON CONFLICT (event_id) DO UPDATE SET
        event_time = EXCLUDED.event_time,
        magnitude = EXCLUDED.magnitude,
        depth_km = EXCLUDED.depth_km,
        event_location_name = EXCLUDED.event_location_name;
"""


def _clean(column: str, value: str):
    value = html.unescape(value).strip()
    if not value:
        return None
    return float(value) if column in NUMERIC_COLUMNS else value


def parse_html(text: str) -> list[dict]:
    """Parsa la tabella "Show table" restituita da earthquakes.php in una lista di dict."""
    rows = []
    for event_id, row_html in ROW_RE.findall(text):
        cells = CELL_RE.findall(row_html)
        if len(cells) < len(COLUMNS):
            print(f"  [WARN] riga con {len(cells)} celle (attese {len(COLUMNS)}), saltata: {event_id}")
            continue
        try:
            row = {col: _clean(col, val) for col, val in zip(COLUMNS, cells)}
        except ValueError:
            print(f"  [WARN] valore numerico non valido, riga saltata: {event_id}")
            continue
        row["event_id"] = event_id
        row["event_time"] = row["event_time"] + "+00:00"  # confermato UTC (vedi docstring)
        rows.append(row)
    return rows


def fetch_chunk(start_date: str, end_date: str) -> list[dict]:
    """Scarica e parsa un intervallo di terremoti (tabella HTML "Show table").
    NB: non aggiungere il campo 'makeFile', risponde sempre 500 (bug del sito)."""
    data = {
        "startDate": start_date,
        "endDate": end_date,
        "orderByField": "datetime",
        "showTable": "on",
    }
    resp = requests.post(BASE_URL, data=data, timeout=120)
    resp.raise_for_status()
    return parse_html(resp.text)


def upsert_rows(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    conn.commit()
    return len(rows)


def run(from_year: int, to_year: int, pause_seconds: float = 1.0) -> None:
    """Scarica anno per anno per evitare risposte troppo grandi in un'unica richiesta
    (~700KB/2300 eventi per un anno tipico)."""
    conn = get_connection()
    total = 0
    try:
        for year in range(from_year, to_year + 1):
            start = f"{year}-01-01"
            end = f"{year}-12-31" if year < date.today().year else date.today().isoformat()
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
    parser = argparse.ArgumentParser(description="Ingestion terremoti EtnaRCSC (INGV-OE)")
    parser.add_argument("--from-year", type=int, default=1999)
    parser.add_argument("--to-year", type=int, default=date.today().year)
    args = parser.parse_args()
    run(args.from_year, args.to_year)
