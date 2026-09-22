"""
Ingestion tremore vulcanico — RMS su forme d'onda scaricate via FDSN dataselect (INGV).

Fonte: rete sismica IV (INGV Osservatorio Etneo), servizi FDSN standard
(https://webservices.ingv.it/fdsnws/dataselect/1/ e /station/1/).

Le stazioni attive sull'Etna cambiano nel tempo (nuovi sensori, dismissioni),
quindi non sono hardcodate: per ogni run si interroga il servizio "station"
per sapere quali stazioni/canali erano effettivamente attivi nel periodo
richiesto (bounding box in config.py), e si sceglie HHZ se disponibile,
altrimenti EHZ (verticale, standard per l'RMS del tremore).

Per ogni giorno e stazione attiva: scarica la traccia giornaliera, applica un
filtro bandpass 0.5-2.5 Hz (coerente con band_hz di default nello schema) e
calcola l'RMS su finestre non sovrapposte (default 10 minuti, lo standard
per il monitoraggio del tremore vulcanico).

NOTA: l'RMS è calcolato sui conteggi grezzi del sensore (nessuna rimozione
della risposte strumentale). Sensori diversi hanno guadagni diversi, quindi
i valori assoluti non sono confrontabili tra stazioni diverse: sono pensati
per seguire l'andamento nel tempo di una singola stazione. Se in EDA servisse
confrontare stazioni tra loro, va aggiunta la rimozione della risposta
(servizio station con level=response + Trace.remove_response()).

Esecuzione:
    python -m ingestion.ingest_tremore --from-date 2024-06-01 --to-date 2024-06-01
"""
import argparse
import io
import time
from datetime import date, datetime, timedelta

import numpy as np
import requests
from obspy import Stream, UTCDateTime, read

from config import ETNA_BBOX
from db.connection import get_connection

STATION_URL = "https://webservices.ingv.it/fdsnws/station/1/query"
DATASELECT_URL = "https://webservices.ingv.it/fdsnws/dataselect/1/query"

NETWORK = "IV"
CHANNELS = "HHZ,EHZ"
CHANNEL_PRIORITY = ["HHZ", "EHZ"]  # HHZ preferito (banda passante più larga) se entrambi disponibili
BAND_HZ = "0.5-2.5"
FREQMIN, FREQMAX = 0.5, 2.5

UPSERT_SQL = """
    INSERT INTO tremore (
        station, window_start, window_end, rms_value, band_hz
    ) VALUES (
        %(station)s, %(window_start)s, %(window_end)s, %(rms_value)s, %(band_hz)s
    )
    ON CONFLICT (station, window_start, band_hz) DO UPDATE SET
        rms_value = EXCLUDED.rms_value,
        window_end = EXCLUDED.window_end;
"""


def _as_utc_iso(t: UTCDateTime) -> str:
    """UTCDateTime.isoformat() non riporta il fuso: senza offset esplicito
    PostgreSQL interpreterebbe il timestamp nel fuso della sessione."""
    return t.isoformat() + "+00:00"


def parse_stations_text(text: str) -> dict[str, dict]:
    """Parsa l'output "text" (pipe-separated) del servizio FDSN station.
    Ritorna {station: {"channel": ..., "start": date, "end": date|None}}."""
    stations: dict[str, dict] = {}
    for line in text.strip().splitlines():
        if not line or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) < 17:
            continue
        station, channel = fields[1], fields[3]
        epoch_start = date.fromisoformat(fields[15][:10])
        epoch_end = date.fromisoformat(fields[16][:10]) if fields[16] else None

        current = stations.get(station)
        if current is None:
            stations[station] = {"channel": channel, "start": epoch_start, "end": epoch_end}
        elif channel == current["channel"]:
            current["start"] = min(current["start"], epoch_start)
            current["end"] = None if (current["end"] is None or epoch_end is None) \
                else max(current["end"], epoch_end)
        elif CHANNEL_PRIORITY.index(channel) < CHANNEL_PRIORITY.index(current["channel"]):
            stations[station] = {"channel": channel, "start": epoch_start, "end": epoch_end}
    return stations


def fetch_active_stations(from_date: date, to_date: date) -> dict[str, dict]:
    """
    Interroga il servizio FDSN station per le stazioni/canali attivi nel periodo
    richiesto sull'area Etna, invece di hardcodare nomi di stazione.
    """
    params = {
        "minlatitude": ETNA_BBOX["min_lat"], "maxlatitude": ETNA_BBOX["max_lat"],
        "minlongitude": ETNA_BBOX["min_lon"], "maxlongitude": ETNA_BBOX["max_lon"],
        "network": NETWORK, "channel": CHANNELS,
        "level": "channel", "format": "text",
        "starttime": from_date.isoformat(),
        "endtime": (to_date + timedelta(days=1)).isoformat(),
    }
    resp = requests.get(STATION_URL, params=params, timeout=60)
    resp.raise_for_status()
    return parse_stations_text(resp.text)


def fetch_waveform(station: str, channel: str, day: date) -> Stream | None:
    """Scarica la traccia miniSEED di un giorno intero. None se non ci sono dati."""
    start = UTCDateTime(f"{day.isoformat()}T00:00:00")
    end = start + 86400
    params = {
        "network": NETWORK, "station": station, "location": "*", "channel": channel,
        "starttime": start.isoformat(), "endtime": end.isoformat(),
    }
    resp = requests.get(DATASELECT_URL, params=params, timeout=120)
    if resp.status_code == 204 or not resp.content:
        return None
    resp.raise_for_status()
    return read(io.BytesIO(resp.content))


def compute_rms_windows(stream: Stream | None, station: str, window_minutes: int) -> list[dict]:
    """Filtra in banda e calcola l'RMS su finestre non sovrapposte, una per stazione."""
    if not stream:
        return []

    stream = stream.copy()
    stream.merge(method=0, fill_value=None)  # unione segmenti; i buchi restano mascherati
    window_seconds = window_minutes * 60

    rows = []
    for segment in stream.split():  # scarta i tratti mascherati, tiene solo quelli continui
        if segment.stats.npts < 2:
            continue
        segment.detrend("linear")
        segment.filter("bandpass", freqmin=FREQMIN, freqmax=FREQMAX, corners=4, zerophase=True)

        t = segment.stats.starttime
        segment_end = segment.stats.endtime
        while t + window_seconds <= segment_end:
            win = segment.slice(t, t + window_seconds)
            if win.stats.npts > 0:
                rms_value = float(np.sqrt(np.mean(win.data.astype("float64") ** 2)))
                rows.append({
                    "station": station,
                    "window_start": _as_utc_iso(t),
                    "window_end": _as_utc_iso(t + window_seconds),
                    "rms_value": rms_value,
                    "band_hz": BAND_HZ,
                })
            t += window_seconds
    return rows


def upsert_rows(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    conn.commit()
    return len(rows)


def run(from_date: date, to_date: date, window_minutes: int = 10, pause_seconds: float = 1.0) -> None:
    print("Ricerca stazioni attive nel periodo richiesto ...")
    stations = fetch_active_stations(from_date, to_date)
    print(f"  {len(stations)} stazioni trovate: {', '.join(sorted(stations))}")

    conn = get_connection()
    total = 0
    try:
        day = from_date
        while day <= to_date:
            active_today = {
                station: info for station, info in stations.items()
                if info["start"] <= day and (info["end"] is None or day <= info["end"])
            }
            print(f"[{day}] {len(active_today)} stazioni attive")
            for station, info in active_today.items():
                try:
                    stream = fetch_waveform(station, info["channel"], day)
                except requests.RequestException as exc:
                    print(f"  [ERRORE] {station}: richiesta fallita: {exc}")
                    time.sleep(pause_seconds)
                    continue

                rows = compute_rms_windows(stream, station, window_minutes)
                n = upsert_rows(conn, rows)
                total += n
                print(f"  {station}: {n} finestre salvate/aggiornate")
                time.sleep(pause_seconds)  # non martellare il servizio pubblico
            day += timedelta(days=1)
    finally:
        conn.close()
    print(f"\nCompletato. Totale finestre processate: {total}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingestion tremore vulcanico area Etna (FDSN dataselect)")
    parser.add_argument("--from-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                         required=True, help="Es. 2024-06-01. Consigliato un giorno di prova prima del backfill.")
    parser.add_argument("--to-date", type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
                         default=date.today())
    parser.add_argument("--window-minutes", type=int, default=10)
    args = parser.parse_args()
    run(args.from_date, args.to_date, args.window_minutes)
