"""
Ingestion terremoti — EtnaRSC (Mt. Etna Revised Seismic Catalog from 2020, INGV-OE).

Prosegue EtnaRCSC: il modulo web EtnaRCSC (ingest_etnarcsc.py) si è fermato al 28/02/2026,
mentre EtnaRSC (https://eqcatalog.ct.ingv.it/etnaRsc/Home.asp) è aggiornato quasi in tempo
reale. Nel periodo in comune (2020-01 -> 2026-02) i due cataloghi coincidono: 7.844 eventi su
7.844 con stessa origine (entro 3 s), stessa magnitudo e profondità (differenza mediana 0.02 km).
Per questo di default si carica solo il periodo NON coperto da EtnaRCSC (da 2026-03-01).

Fonte: CSV completo https://eqcatalog.ct.ingv.it/filedb/csv/all_etna.csv, orari in UTC.
Colonne: Origin Time;Ml;Zone;Depth;Latitude;Longitude;Nl;Gap;RMS;seh;sez;Note;Processing.
Particolarità: codifica latin-1; il campo Note può contenere ';' o andare a capo (righe di
continuazione); gli eventi non localizzati ("Imp. Loc.") non hanno Ml/profondità/coordinate e
vengono scartati. Il CSV non ha un id evento: event_id = "etnarsc_" + origin time + lat + lon (più eventi possono
avere lo stesso secondo di origine).

Gli eventi più recenti possono essere ancora in revisione: di default si esclude l'ultima
settimana (--to-date).

Esecuzione:
    python -m ingestion.ingest_etnarsc
    python -m ingestion.ingest_etnarsc --from-date 2026-03-01 --to-date 2026-09-14

Citazione: Barberi, G., Di Grazia, G., Ferrari, F., et al. — Mt. Etna Revised Seismic Catalog
from 2020 (INGV-OE), CC BY 4.0. Riferimenti completi nella pagina del catalogo.
"""
import argparse
import re
from datetime import date, datetime, timedelta

import requests

from db.connection import get_connection

CSV_URL = "https://eqcatalog.ct.ingv.it/filedb/csv/all_etna.csv"
ROW_START = re.compile(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2};")

UPSERT_SQL = """
    INSERT INTO terremoti (
        event_id, event_time, latitude, longitude, depth_km,
        magnitude, mag_type, author, catalog, event_location_name, source
    ) VALUES (
        %(event_id)s, %(event_time)s, %(latitude)s, %(longitude)s, %(depth_km)s,
        %(magnitude)s, 'ML', 'INGV-OE', 'EtnaRSC', %(region)s, 'EtnaRSC'
    )
    ON CONFLICT (event_id) DO UPDATE SET
        event_time = EXCLUDED.event_time,
        magnitude = EXCLUDED.magnitude,
        depth_km = EXCLUDED.depth_km,
        latitude = EXCLUDED.latitude,
        longitude = EXCLUDED.longitude,
        event_location_name = EXCLUDED.event_location_name;
"""


def _num(value: str):
    value = value.strip()
    return float(value) if value else None


def parse_csv(text: str) -> list[dict]:
    """Parsa il CSV EtnaRSC. Unisce le righe di continuazione del campo Note e scarta gli
    eventi non localizzati (senza magnitudo, profondità o coordinate)."""
    lines = text.splitlines()[1:]  # intestazione
    records: list[str] = []
    for line in lines:
        if ROW_START.match(line):
            records.append(line)
        elif records and line.strip():
            records[-1] += " " + line
    rows = []
    for rec in records:
        fields = rec.split(";")
        if len(fields) < 6:
            continue
        origin, ml, zone, depth, lat, lon = (f.strip() for f in fields[:6])
        try:
            magnitude, depth_km, latitude, longitude = _num(ml), _num(depth), _num(lat), _num(lon)
        except ValueError:
            continue
        if None in (magnitude, depth_km, latitude, longitude):
            continue
        rows.append({
            "event_id": f"etnarsc_{origin.replace('/', '-').replace(' ', 'T')}_{lat}_{lon}",
            "event_time": origin.replace("/", "-") + "+00:00",  # orari UTC
            "magnitude": magnitude, "depth_km": depth_km,
            "latitude": latitude, "longitude": longitude,
            "region": zone or None,
        })
    return rows


def fetch_all() -> list[dict]:
    resp = requests.get(CSV_URL, timeout=120)
    resp.raise_for_status()
    return parse_csv(resp.content.decode("latin-1"))


def run(from_date: date, to_date: date) -> None:
    rows = [r for r in fetch_all()
            if from_date <= datetime.fromisoformat(r["event_time"]).date() <= to_date]
    print(f"{len(rows)} eventi localizzati tra {from_date} e {to_date}")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
        conn.commit()
    finally:
        conn.close()
    print("Completato.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingestion terremoti EtnaRSC (INGV-OE, da 2020)")
    parser.add_argument("--from-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        default=date(2026, 3, 1),
                        help="Default: primo giorno non coperto da EtnaRCSC")
    parser.add_argument("--to-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                        default=date.today() - timedelta(days=7))
    args = parser.parse_args()
    run(args.from_date, args.to_date)
