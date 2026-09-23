"""
Costruzione del dataset giornaliero per la classificazione "eruzione nelle prossime 24h".

Unità di campionamento: un giorno D (UTC). Le feature usano solo terremoti EtnaRCSC
con event_time < fine del giorno D (nessuna informazione dal futuro). Etichetta:
1 se il giorno D+1 contiene l'inizio di un'eruzione (eventi_noti, tipo 'eruzione_*').

Limite noto: gli eventi hanno solo la data (senza ora), quindi "24h" = "giorno successivo".

Negativi: si scartano i giorni con un'eruzione entro `min_gap_days` giorni dal giorno
target D+1 (default 60, come richiesto), per non contaminare i controlli con la
fase pre/post eruttiva. Con serie fitte di parossismi (es. 2021) questo elimina molti giorni.

Feature (finestre finali di 7, 30 e 90 giorni):
- n_all_*, n_mc_* : conteggio eventi totali / con M >= Mc (completezza)
- log10_energy_*  : log10 dell'energia sismica cumulata (E = 10^(1.5 M + 4.8) J)
- benioff_*       : deformazione di Benioff cumulata sqrt(E)
- b_value_90d     : b-value di Aki-Utsu su 90 giorni (30 gg darebbe quasi sempre NaN con Mc=1.5) (NaN se < min_events_b eventi con M >= Mc)

Esecuzione:
    python -m features.build_dataset
    python -m features.build_dataset --mc 1.4 --min-gap-days 60 --out data_out/dataset_24h.csv
"""
import argparse
import os

import numpy as np
import pandas as pd

from db.connection import get_connection

WINDOWS = (7, 30, 90)
MAG_BIN = 0.1


def estimate_mc(mags: pd.Series) -> float:
    """Magnitudo di completezza: massima curvatura + 0.2 (correzione usuale)."""
    counts = mags.round(1).value_counts()
    return round(float(counts.idxmax()) + 0.2, 1)


def b_value_aki(mags: np.ndarray, mc: float) -> float:
    """Stima di massima verosimiglianza (Aki-Utsu) con correzione per magnitudo binnata."""
    m = mags[mags >= mc]
    if len(m) == 0:
        return np.nan
    denom = m.mean() - (mc - MAG_BIN / 2)
    return np.log10(np.e) / denom if denom > 0 else np.nan


def load_earthquakes(conn, source: str = "EtnaRCSC") -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT event_time, magnitude, latitude, longitude, depth_km FROM terremoti "
        "WHERE source = %(s)s AND magnitude IS NOT NULL ORDER BY event_time",
        conn, params={"s": source},
    )
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
    return df


def load_eruption_dates(conn) -> pd.DatetimeIndex:
    df = pd.read_sql(
        "SELECT DISTINCT event_date FROM eventi_noti WHERE event_type LIKE 'eruzione%%'", conn
    )
    return pd.DatetimeIndex(pd.to_datetime(df["event_date"])).sort_values()


def build_features(eq: pd.DataFrame, days: pd.DatetimeIndex, mc: float,
                   min_events_b: int = 30) -> pd.DataFrame:
    """Feature per ogni giorno in `days` (UTC, mezzanotte), calcolate sui dati fino a fine giornata."""
    times = eq["event_time"].dt.tz_convert("UTC").dt.tz_localize(None).values.astype("datetime64[ns]")
    mags = eq["magnitude"].to_numpy(dtype=float)
    energy = 10.0 ** (1.5 * mags + 4.8)
    rows = []
    for day in days:
        end = np.datetime64(day + pd.Timedelta(days=1))
        hi = np.searchsorted(times, end, side="left")
        row = {"day": day}
        for w in WINDOWS:
            lo = np.searchsorted(times, end - np.timedelta64(w, "D"), side="left")
            m, e = mags[lo:hi], energy[lo:hi]
            row[f"n_all_{w}d"] = len(m)
            row[f"n_mc_{w}d"] = int((m >= mc).sum())
            row[f"log10_energy_{w}d"] = np.log10(e.sum()) if len(e) else np.nan
            row[f"benioff_{w}d"] = np.sqrt(e).sum() if len(e) else 0.0
            if w == 90:
                row["b_value_90d"] = (
                    b_value_aki(m, mc) if (m >= mc).sum() >= min_events_b else np.nan
                )
        rows.append(row)
    out = pd.DataFrame(rows).set_index("day")
    out["n_mc_ratio_7_30"] = out["n_mc_7d"] / out["n_mc_30d"].replace(0, np.nan)
    return out


def label_days(days: pd.DatetimeIndex, eruptions: pd.DatetimeIndex, min_gap_days: int) -> pd.DataFrame:
    """label=1 se D+1 è un giorno di eruzione; giorni ambigui (eruzione entro min_gap_days) esclusi."""
    eruption_set = set(eruptions)
    target = days + pd.Timedelta(days=1)
    label = np.array([t in eruption_set for t in target], dtype=int)
    er = eruptions.values.astype("datetime64[D]")
    keep = np.ones(len(days), dtype=bool)
    for i, t in enumerate(target.values.astype("datetime64[D]")):
        if label[i] == 0:
            gap = np.abs((er - t).astype(int)).min() if len(er) else 10**6
            keep[i] = gap >= min_gap_days
    out = pd.DataFrame({"label": label, "keep": keep}, index=days)
    return out


def build_dataset(conn, start: str, end: str | None, mc: float | None, min_gap_days: int):
    eq = load_earthquakes(conn)
    eruptions = load_eruption_dates(conn)
    last_eq_day = eq["event_time"].max().tz_convert("UTC").tz_localize(None).normalize()
    # ultimo giorno utilizzabile: il catalogo ha ritardo, e D+1 deve stare nel periodo coperto
    end_day = min(pd.Timestamp(end), last_eq_day - pd.Timedelta(days=1)) if end else last_eq_day - pd.Timedelta(days=1)
    days = pd.date_range(start, end_day, freq="D")
    if mc is None:
        mc = estimate_mc(eq.loc[eq["event_time"] >= pd.Timestamp(start, tz="UTC"), "magnitude"])
    feats = build_features(eq, days, mc)
    labels = label_days(days, eruptions, min_gap_days)
    data = feats.join(labels)
    return data, mc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset giornaliero eruzione-nelle-prossime-24h")
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--mc", type=float, default=None, help="Magnitudo di completezza (default: stimata)")
    parser.add_argument("--min-gap-days", type=int, default=60)
    parser.add_argument("--out", default="data_out/dataset_24h.csv")
    args = parser.parse_args()

    conn = get_connection()
    try:
        data, mc = build_dataset(conn, args.start, args.end, args.mc, args.min_gap_days)
    finally:
        conn.close()

    total = len(data)
    kept = data[data["keep"]]
    print(f"Mc usata: {mc}")
    print(f"Periodo: {data.index.min().date()} -> {data.index.max().date()}  ({total} giorni)")
    print(f"Positivi (eruzione il giorno dopo): {int(data['label'].sum())}")
    print(f"Negativi tenuti (>= {args.min_gap_days} gg da eruzioni): {int(((data['label'] == 0) & data['keep']).sum())}")
    print(f"Negativi scartati per vicinanza: {int(((data['label'] == 0) & ~data['keep']).sum())}")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    kept.drop(columns="keep").to_csv(args.out)
    print(f"Scritto {len(kept)} righe in {args.out}")
