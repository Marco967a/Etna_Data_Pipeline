"""
Test offline dei parser: nessuna rete e nessun database.
Esecuzione (dalla root del progetto): pytest
"""
import pandas as pd
import pytest

from ingestion.ingest_hotspot import DB_COLUMNS, normalize_hotspot_df
from ingestion.ingest_terremoti import COLUMNS, parse_text

ISIDE_HEADER = "#EventID|Time|Latitude|Longitude|Depth/Km|Author|Catalog|Contributor|ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType"


def test_parse_text_converte_tipi_e_campi_vuoti():
    text = "\n".join([
        ISIDE_HEADER,
        "1|2018-12-26T02:19:14.000000|37.7|15.1|1.2|SURVEY-INGV|INGV|INGV|1|ML|4.9|INGV|Etna|earthquake",
        # profondità e magnitudo mancanti
        "2|2018-12-26T03:00:00.000000|37.7|15.1||SURVEY-INGV|INGV|INGV|2||||Etna|earthquake",
    ])
    rows = parse_text(text)

    assert len(rows) == 2
    assert rows[0]["magnitude"] == 4.9
    assert rows[0]["depth_km"] == 1.2
    assert rows[0]["event_id"] == "1"
    assert rows[1]["depth_km"] is None
    assert rows[1]["magnitude"] is None
    assert rows[1]["mag_type"] is None
    assert set(rows[0]) == set(COLUMNS)


def test_parse_text_salta_righe_malformate(capsys):
    text = "\n".join([
        ISIDE_HEADER,
        "solo|tre|campi",
        "3|2020-01-01T00:00:00|non_un_numero|15.1|1.0|A|B|C|3|ML|2.0|D|Etna|earthquake",
        "4|2020-01-01T00:00:00|37.7|15.1|1.0|A|B|C|4|ML|2.0|D|Etna|earthquake",
    ])
    rows = parse_text(text)

    assert [r["event_id"] for r in rows] == ["4"]
    assert capsys.readouterr().out.count("[WARN]") == 2


def test_parse_text_risposta_vuota():
    assert parse_text("") == []


MODIS_CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight
37.75,15.0,330.1,1.0,1.0,2012-01-20,0035,Terra,MODIS,85,6.1,290.2,12.5,N
37.76,15.0,320.0,1.0,1.0,2012-01-20,1210,Aqua,MODIS,40,6.1,288.0,,D
"""

VIIRS_CSV = """latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_ti5,frp,daynight
37.75,15.0,330.1,0.4,0.4,2012-01-20,0035,N,VIIRS,n,1.0NRT,290.2,3.1,N
"""


def test_normalize_hotspot_mantiene_acq_time_a_4_cifre():
    df = normalize_hotspot_df(MODIS_CSV, "MODIS")

    assert list(df.columns) == DB_COLUMNS
    assert df["acq_time"].tolist() == ["0035", "1210"]


def test_normalize_hotspot_nan_diventa_none():
    df = normalize_hotspot_df(MODIS_CSV, "MODIS")
    records = df.to_dict("records")

    assert records[0]["frp"] == 12.5
    assert records[1]["frp"] is None
    assert records[0]["confidence"] == "85"


def test_normalize_hotspot_viirs_confidence_lettera_e_instrument():
    df = normalize_hotspot_df(VIIRS_CSV, "VIIRS")

    assert df.iloc[0]["confidence"] == "n"
    assert df.iloc[0]["instrument"] == "VIIRS"


def test_normalize_hotspot_csv_vuoto():
    df = normalize_hotspot_df("", "MODIS")

    assert df.empty
    assert list(df.columns) == DB_COLUMNS


def test_normalize_hotspot_errore_firms_con_status_200():
    with pytest.raises(ValueError, match="colonne mancanti"):
        normalize_hotspot_df("Invalid MAP_KEY.", "MODIS")
