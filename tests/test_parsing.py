"""
Test offline dei parser: nessuna rete e nessun database.
Esecuzione (dalla root del progetto): pytest
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest
from obspy import Stream, Trace

from ingestion.ingest_hotspot import DB_COLUMNS, normalize_hotspot_df
from ingestion.ingest_terremoti import COLUMNS, parse_text
from ingestion.ingest_tremore import compute_rms_windows, parse_stations_text

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


def test_parse_text_orario_senza_fuso_e_utc():
    text = "5|2024-01-03T06:00:20.910000|37.6|14.9|7|A|B|C|5|ML|1.6|D|Etna|earthquake"

    assert parse_text(text)[0]["event_time"] == "2024-01-03T06:00:20.910000+00:00"


def test_parse_text_orario_con_fuso_resta_invariato():
    text = "6|2024-01-03T06:00:20Z|37.6|14.9|7|A|B|C|6|ML|1.6|D|Etna|earthquake"

    assert parse_text(text)[0]["event_time"] == "2024-01-03T06:00:20Z"


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


def _synthetic_trace(seconds: float, amplitude: float = 1000.0, freq: float = 1.0,
                      sampling_rate: float = 100.0, start="2024-01-01T00:00:00"):
    """Traccia sinusoidale sintetica (entro la banda 0.5-2.5 Hz) per testare l'RMS."""
    from obspy import UTCDateTime

    npts = int(seconds * sampling_rate)
    t = np.arange(npts) / sampling_rate
    data = (amplitude * np.sin(2 * np.pi * freq * t)).astype("float64")
    return Trace(data=data, header={"sampling_rate": sampling_rate, "starttime": UTCDateTime(start)})


def test_compute_rms_windows_su_sinusoide_nota():
    # 1300s di segnale a 1 Hz (dentro la banda 0.5-2.5) -> 2 finestre da 600s piene,
    # la terza (1800s) supera la durata della traccia e va scartata.
    stream = Stream([_synthetic_trace(seconds=1300)])

    rows = compute_rms_windows(stream, "TEST", window_minutes=10)

    assert len(rows) == 2
    assert all(row["station"] == "TEST" for row in rows)
    assert all(row["band_hz"] == "0.5-2.5" for row in rows)
    assert all(row["window_start"].endswith("+00:00") for row in rows)
    # RMS atteso di una sinusoide pura: ampiezza / sqrt(2)
    for row in rows:
        assert row["rms_value"] == pytest.approx(1000.0 / 2**0.5, rel=0.05)


def test_compute_rms_windows_scarta_segmenti_piu_corti_della_finestra():
    # Due segmenti separati da un buco, entrambi più corti della finestra (600s):
    # nessuna finestra piena, quindi nessuna riga (niente RMS spurio a cavallo del buco).
    from obspy import UTCDateTime

    trace1 = _synthetic_trace(seconds=300, start="2024-01-01T00:00:00")
    trace2 = _synthetic_trace(seconds=300, start="2024-01-01T00:06:40")  # buco di 100s
    stream = Stream([trace1, trace2])

    assert compute_rms_windows(stream, "TEST", window_minutes=10) == []


def test_compute_rms_windows_stream_vuoto():
    assert compute_rms_windows(None, "TEST", window_minutes=10) == []
    assert compute_rms_windows(Stream(), "TEST", window_minutes=10) == []


STATION_HEADER = (
    "#Network|Station|location|Channel|Latitude|Longitude|Elevation|Depth|"
    "Azimuth|Dip|SensorDescription|Scale|ScaleFreq|ScaleUnits|SampleRate|StartTime|EndTime"
)


def test_parse_stations_text_stazione_attiva_senza_fine():
    text = "\n".join([
        STATION_HEADER,
        "IV|ECPN||HHZ|37.74|14.98|3038|0|0|-90|SENSOR|1|1|m/s|100|2020-06-16T12:32:09|",
    ])

    stations = parse_stations_text(text)

    assert stations == {"ECPN": {"channel": "HHZ", "start": date(2020, 6, 16), "end": None}}


def test_parse_stations_text_unisce_epoche_dello_stesso_canale():
    text = "\n".join([
        "IV|ECPN||HHZ|37.74|14.98|3038|0|0|-90|SENSOR|1|1|m/s|100|2020-06-16T12:32:09|2022-01-01T00:00:00",
        "IV|ECPN||HHZ|37.74|14.98|3038|0|0|-90|SENSOR2|1|1|m/s|100|2022-01-02T00:00:00|",
    ])

    stations = parse_stations_text(text)

    assert stations["ECPN"] == {"channel": "HHZ", "start": date(2020, 6, 16), "end": None}


def test_parse_stations_text_preferisce_hhz_a_ehz():
    text = "\n".join([
        "IV|ECPN||EHZ|37.74|14.98|3038|0|0|-90|OLD|1|1|m/s|50|2010-01-01T00:00:00|2020-01-01T00:00:00",
        "IV|ECPN||HHZ|37.74|14.98|3038|0|0|-90|NEW|1|1|m/s|100|2020-01-02T00:00:00|",
    ])

    stations = parse_stations_text(text)

    assert stations["ECPN"]["channel"] == "HHZ"
    assert stations["ECPN"]["start"] == date(2020, 1, 2)


def test_parse_stations_text_righe_malformate_e_vuoto():
    assert parse_stations_text("") == {}
    assert parse_stations_text("IV|ECPN|solo|tre|campi") == {}
