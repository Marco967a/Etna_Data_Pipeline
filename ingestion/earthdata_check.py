"""
Verifica delle credenziali NASA Earthdata e ricerca di prova sull'area Etna (earthaccess).

Non scrive nulla nel database: serve a controllare che l'account Earthdata funzioni
e a vedere quali granuli sono disponibili prima di scegliere un dataset da integrare.

Credenziali: EARTHDATA_USERNAME + EARTHDATA_PASSWORD (oppure EARTHDATA_TOKEN) nel file .env.
La ricerca su CMR è pubblica; è il download a richiedere il login, quindi
--download è la prova reale che le credenziali funzionano.

Esecuzione:
    python -m ingestion.earthdata_check
    python -m ingestion.earthdata_check --short-name MOD11A1 --from-date 2024-01-01 --to-date 2024-01-10
    python -m ingestion.earthdata_check --download
"""
import argparse
from datetime import date, datetime
from pathlib import Path

import earthaccess
from earthaccess.exceptions import LoginAttemptFailure, LoginStrategyUnavailable

from config import (
    EARTHDATA_PASSWORD,
    EARTHDATA_TOKEN,
    EARTHDATA_USERNAME,
    ETNA_BBOX,
)

# MODIS Terra Land Surface Temperature giornaliera; il tile h19v05 copre l'Etna.
DEFAULT_SHORT_NAME = "MOD11A1"
DOWNLOAD_DIR = Path("data_raw")  # ignorata da git


def login() -> earthaccess.Auth:
    if not ((EARTHDATA_USERNAME and EARTHDATA_PASSWORD) or EARTHDATA_TOKEN):
        raise SystemExit(
            "Credenziali Earthdata mancanti: imposta EARTHDATA_USERNAME e EARTHDATA_PASSWORD "
            "(oppure EARTHDATA_TOKEN) nel file .env"
        )
    try:
        auth = earthaccess.login(strategy="environment")
    except (LoginStrategyUnavailable, LoginAttemptFailure) as exc:
        raise SystemExit(f"Login Earthdata fallito: {exc}")
    if not auth.authenticated:
        raise SystemExit("Login Earthdata fallito: credenziali non accettate")
    return auth


def search(short_name: str, from_date: date, to_date: date, count: int) -> list:
    bbox = (ETNA_BBOX["min_lon"], ETNA_BBOX["min_lat"], ETNA_BBOX["max_lon"], ETNA_BBOX["max_lat"])
    return earthaccess.search_data(
        short_name=short_name,
        bounding_box=bbox,
        temporal=(from_date.isoformat(), to_date.isoformat()),
        count=count,
    )


def run(short_name: str, from_date: date, to_date: date, count: int, download: bool) -> None:
    login()
    print("Login Earthdata riuscito.")

    print(f"Ricerca {short_name} sull'area Etna, {from_date} -> {to_date} (max {count} granuli) ...")
    granules = search(short_name, from_date, to_date, count)
    if not granules:
        print("Nessun granulo trovato: controlla short-name e intervallo di date.")
        return
    print(f"{len(granules)} granuli trovati:")
    for granule in granules:
        print(f"  {granule['umm']['GranuleUR']}")

    if download:
        DOWNLOAD_DIR.mkdir(exist_ok=True)
        print(f"Download del primo granulo in {DOWNLOAD_DIR}/ ...")
        paths = earthaccess.download(granules[:1], DOWNLOAD_DIR)
        print(f"Scaricato: {', '.join(str(p) for p in paths)}")


if __name__ == "__main__":
    parse_date = lambda s: datetime.strptime(s, "%Y-%m-%d").date()
    parser = argparse.ArgumentParser(description="Verifica Earthdata e ricerca di prova sull'Etna")
    parser.add_argument("--short-name", default=DEFAULT_SHORT_NAME,
                        help=f"short name del prodotto su CMR (default {DEFAULT_SHORT_NAME})")
    parser.add_argument("--from-date", type=parse_date, default=date(2024, 1, 1))
    parser.add_argument("--to-date", type=parse_date, default=date(2024, 1, 10))
    parser.add_argument("--count", type=int, default=5, help="numero massimo di granuli da elencare")
    parser.add_argument("--download", action="store_true",
                        help="scarica il primo granulo in data_raw/ come prova del login")
    args = parser.parse_args()
    run(args.short_name, args.from_date, args.to_date, args.count, args.download)
