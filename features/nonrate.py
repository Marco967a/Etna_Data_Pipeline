"""
Feature "non legate al tasso": descrivono COME sono i terremoti (profondità, posizione,
magnitudo, regolarità temporale), non QUANTI sono. Servono a evitare il confondente della
non stazionarietà del catalogo (numero di eventi legato a rete/rilevabilità).

Per ogni giorno D e finestra finale W (7, 30, 90 giorni; solo dati fino a fine D), se ci sono
almeno MIN_EVENTS eventi:
- depth_med_W, depth_iqr_W, frac_deep_W (quota di eventi con profondità > DEEP_KM)
- dist_summit_med_W: distanza mediana dall'asse dei crateri sommitali (km)
- disp_km_W: dispersione spaziale (deviazione std delle distanze dal centroide, km)
- mag_mean_W, mag_std_W
- cv_dt_W: coefficiente di variazione dei tempi tra eventi (>1 = clustering, ~1 = Poisson)
Migrazione (ultimi 7 gg vs giorni 8-37):
- shift_km_7v30: distanza tra centroidi; depth_shift_7v30: differenza di profondità mediana
b-value con Mc locale:
- b_local_90d: Aki-Utsu su 90 gg con Mc = massima curvatura + 0.2 stimata sull'ultimo anno
"""
import numpy as np
import pandas as pd

from features.build_dataset import b_value_aki

SUMMIT = (37.751, 14.994)  # lat, lon approssimative dell'area dei crateri sommitali
DEEP_KM = 10.0
MIN_EVENTS = 5
MIN_EVENTS_CV = 10
WINDOWS = (7, 30, 90)


def to_km(lat: np.ndarray, lon: np.ndarray, ref=SUMMIT):
    x = (lon - ref[1]) * np.cos(np.radians(ref[0])) * 111.32
    y = (lat - ref[0]) * 110.57
    return x, y


def _window_stats(m, d, x, y, t):
    out = {}
    n = len(m)
    keys = ["depth_med", "depth_iqr", "frac_deep", "dist_summit_med", "disp_km",
            "mag_mean", "mag_std", "cv_dt"]
    if n < MIN_EVENTS:
        return {k: np.nan for k in keys}
    out["depth_med"] = np.median(d)
    out["depth_iqr"] = np.subtract(*np.percentile(d, [75, 25]))
    out["frac_deep"] = float((d > DEEP_KM).mean())
    out["dist_summit_med"] = float(np.median(np.hypot(x, y)))
    out["disp_km"] = float(np.hypot(x - x.mean(), y - y.mean()).std())
    out["mag_mean"] = m.mean()
    out["mag_std"] = m.std()
    if n >= MIN_EVENTS_CV:
        dt = np.diff(t).astype("timedelta64[s]").astype(float)
        out["cv_dt"] = dt.std() / dt.mean() if dt.mean() > 0 else np.nan
    else:
        out["cv_dt"] = np.nan
    return out


def _mc_maxc(m):
    counts = pd.Series(np.round(m, 1)).value_counts()
    return round(float(counts.idxmax()) + 0.2, 1)


def build_nonrate_features(eq: pd.DataFrame, days: pd.DatetimeIndex, min_events_b: int = 30) -> pd.DataFrame:
    t = eq["event_time"].dt.tz_convert("UTC").dt.tz_localize(None).values.astype("datetime64[ns]")
    mags = eq["magnitude"].to_numpy(float)
    depth = eq["depth_km"].to_numpy(float)
    x, y = to_km(eq["latitude"].to_numpy(float), eq["longitude"].to_numpy(float))
    rows = []
    for day in days:
        end = np.datetime64(day + pd.Timedelta(days=1))
        hi = np.searchsorted(t, end, side="left")
        row = {"day": day}
        for w in WINDOWS:
            lo = np.searchsorted(t, end - np.timedelta64(w, "D"), side="left")
            stats = _window_stats(mags[lo:hi], depth[lo:hi], x[lo:hi], y[lo:hi], t[lo:hi])
            row.update({f"{k}_{w}d": v for k, v in stats.items()})
        lo7 = np.searchsorted(t, end - np.timedelta64(7, "D"), side="left")
        lo37 = np.searchsorted(t, end - np.timedelta64(37, "D"), side="left")
        if hi - lo7 >= MIN_EVENTS and lo7 - lo37 >= MIN_EVENTS:
            row["shift_km_7v30"] = float(np.hypot(x[lo7:hi].mean() - x[lo37:lo7].mean(),
                                                  y[lo7:hi].mean() - y[lo37:lo7].mean()))
            row["depth_shift_7v30"] = float(np.median(depth[lo7:hi]) - np.median(depth[lo37:lo7]))
        lo90 = np.searchsorted(t, end - np.timedelta64(90, "D"), side="left")
        lo365 = np.searchsorted(t, end - np.timedelta64(365, "D"), side="left")
        if hi - lo365 >= 200:
            mc = _mc_maxc(mags[lo365:hi])
            m90 = mags[lo90:hi]
            if (m90 >= mc).sum() >= min_events_b:
                row["b_local_90d"] = b_value_aki(m90, mc)
        rows.append(row)
    return pd.DataFrame(rows).set_index("day")
