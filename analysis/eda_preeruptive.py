"""
Analisi esplorativa dei pattern pre-eruttivi (solo terremoti EtnaRCSC + eventi noti).

Approccio: prima statistica descrittiva/inferenziale con test di permutazione (nessuna
assunzione distribuzionale), poi modelli semplici con validazione a blocchi per verificare
se le feature contengono informazione OLTRE il caso e OLTRE il confondente "anno 2021".

1. Epoch sovrapposte: per ogni INIZIO di fase eruttiva (eruzioni separate da > PHASE_GAP giorni
   sono fasi distinte) si confrontano le finestre di W giorni precedenti con date casuali
   "quiete" (nessuna eruzione nei 30 gg prima e nei W..30 gg dopo). p-value empirico a due code,
   correzione di Holm sull'intera griglia di test.
2. Modello A (24h, tutti gli episodi) e Modello B (7 giorni prima dell'inizio di una fase),
   regressione logistica e random forest, GroupKFold per fase/blocchi, AUC vs null da
   permutazione delle etichette a blocchi.

Esecuzione:
    python -m analysis.eda_preeruptive
Output: reports/ (figure PNG + tabelle CSV).
"""
import os
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from db.connection import get_connection
from features.build_dataset import (build_dataset, estimate_mc, load_earthquakes,
                                    load_eruption_dates)

warnings.filterwarnings("ignore")
RNG = np.random.default_rng(42)
OUT = "reports"
START = "2021-01-01"
PHASE_GAP = 30
WINDOWS = (1, 3, 7, 14, 30)
N_NULL = 5000


def daily_metrics(eq: pd.DataFrame, mc: float, start: str, end: pd.Timestamp) -> pd.DataFrame:
    t = eq["event_time"].dt.tz_convert("UTC").dt.tz_localize(None)
    df = pd.DataFrame({"t": t, "m": eq["magnitude"].values})
    df["e"] = 10.0 ** (1.5 * df["m"] + 4.8)
    df["day"] = df["t"].dt.normalize()
    g = df.groupby("day")
    out = pd.DataFrame({
        "n_all": g.size(),
        "n_mc": df[df["m"] >= mc].groupby("day").size(),
        "log10_energy": np.log10(g["e"].sum()),
        "benioff": g["e"].apply(lambda x: np.sqrt(x).sum()),
        "max_mag": g["m"].max(),
    })
    idx = pd.date_range(pd.Timestamp(start) - pd.Timedelta(days=120), end, freq="D")
    out = out.reindex(idx)
    out[["n_all", "n_mc", "benioff"]] = out[["n_all", "n_mc", "benioff"]].fillna(0)
    out["log10_energy"] = out["log10_energy"].fillna(out["log10_energy"].min())
    out["max_mag"] = out["max_mag"].fillna(out["max_mag"].min())
    # tassi relativi alla media mobile annuale: neutralizza i cambi di rete/rilevabilita nel tempo
    for c in ("n_all", "n_mc"):
        base = out[c].rolling(365, center=True, min_periods=120).mean()
        out[f"{c}_rel"] = out[c] / base
    return out


def phase_onsets(eruptions: pd.DatetimeIndex, start: str, end: pd.Timestamp) -> pd.DatetimeIndex:
    er = eruptions.sort_values()
    onset = [d for i, d in enumerate(er) if i == 0 or (d - er[i - 1]).days > PHASE_GAP]
    return pd.DatetimeIndex([d for d in onset if pd.Timestamp(start) <= d <= end])


def holm(p: np.ndarray) -> np.ndarray:
    order = np.argsort(p)
    adj = np.empty_like(p)
    running = 0.0
    m = len(p)
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj


def epoch_tests(daily: pd.DataFrame, onsets: pd.DatetimeIndex, eruptions: pd.DatetimeIndex,
                start: str, end: pd.Timestamp) -> pd.DataFrame:
    er = eruptions.values.astype("datetime64[D]")
    days = pd.date_range(pd.Timestamp(start), end - pd.Timedelta(days=1), freq="D")
    dv = days.values.astype("datetime64[D]")
    # data di controllo: nessuna eruzione da 30 giorni prima a 30 giorni dopo
    ok = np.array([not ((er >= d - 30) & (er <= d + 30)).any() for d in dv])
    pool = days[ok]
    metrics = ["n_all", "n_mc", "n_all_rel", "n_mc_rel", "log10_energy", "benioff", "max_mag"]
    rows = []
    for w in WINDOWS:
        roll = {m: daily[m].rolling(w).mean() for m in metrics}  # media dei w giorni che finiscono in d
        for m in metrics:
            r = roll[m]
            obs_vals = r.reindex(onsets - pd.Timedelta(days=1)).values  # finestra finisce il giorno prima
            obs = np.nanmean(obs_vals)
            pool_vals = r.reindex(pool - pd.Timedelta(days=0)).values
            pool_vals = pool_vals[~np.isnan(pool_vals)]
            null = np.array([RNG.choice(pool_vals, size=len(onsets)).mean() for _ in range(N_NULL)])
            p = (1 + np.sum(np.abs(null - null.mean()) >= abs(obs - null.mean()))) / (N_NULL + 1)
            rows.append({"metrica": m, "finestra_giorni": w, "media_pre_onset": obs,
                         "media_controlli": null.mean(), "percentile_null": (null < obs).mean() * 100,
                         "p_value": p})
    res = pd.DataFrame(rows)
    res["p_holm"] = holm(res["p_value"].values)
    return res, pool


def plot_epoch(daily, onsets, pool, metric, path, mc):
    lags = np.arange(-60, 6)
    def curve(dates):
        arr = np.array([[daily[metric].get(d + pd.Timedelta(days=int(l)), np.nan) for l in lags] for d in dates])
        return arr
    obs = curve(onsets)
    obs_mean = np.nanmean(obs, axis=0)
    null = np.array([np.nanmean(curve(RNG.choice(pool, len(onsets))), axis=0) for _ in range(400)])
    lo, hi = np.percentile(null, [2.5, 97.5], axis=0)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.fill_between(lags, lo, hi, color="0.8", label="controlli casuali (95%)")
    ax.plot(lags, obs_mean, color="C3", lw=2, label=f"inizio fase (n={len(onsets)})")
    ax.axvline(0, color="k", ls="--", lw=0.8)
    ax.set_xlabel("giorni rispetto all'inizio della fase eruttiva")
    ax.set_ylabel(f"media giornaliera: {metric}")
    ax.legend()
    ax.set_title(f"Epoch sovrapposte - {metric} (Mc={mc})")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def models(conn, mc, onsets):
    data, _ = build_dataset(conn, START, None, mc, min_gap_days=60)
    return data


def cv_eval(X, y, groups, make_model, n_splits=5):
    oof = np.full(len(y), np.nan)
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        if y[tr].sum() == 0 or y[te].sum() == 0:
            continue
        model = make_model()
        model.fit(X.iloc[tr], y[tr])
        oof[te] = model.predict_proba(X.iloc[te])[:, 1]
    ok = ~np.isnan(oof)
    return oof, ok


def perm_null_auc(oof, y, groups, ok, n=300):
    """Null: etichette permutate tra i blocchi (si mantiene la struttura temporale dei gruppi)."""
    aucs = []
    ug = pd.Series(groups).unique()
    gy = pd.Series(y).groupby(groups).mean()
    for _ in range(n):
        shuffled = dict(zip(ug, RNG.permutation(gy.reindex(ug).values)))
        # etichette intra-blocco riallocate a caso mantenendo la frazione di positivi del blocco
        yp = y.copy()
        for g in ug:
            idx = np.where(groups == g)[0]
            yp[idx] = RNG.permutation(y[idx])
        aucs.append(roc_auc_score(yp[ok], oof[ok]))
    return np.array(aucs)


def run_models(data, phase_of_day, onsets):
    feats = [c for c in data.columns if c not in ("label", "keep")]
    kept = data[data["keep"]].copy()
    X = kept[feats]
    results = []
    mk = {
        "logistica": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                           LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced")),
        "random_forest": lambda: make_pipeline(SimpleImputer(strategy="median"),
                                               RandomForestClassifier(300, min_samples_leaf=5, max_depth=4,
                                                                      class_weight="balanced_subsample",
                                                                      random_state=0, n_jobs=-1)),
    }
    # Modello A: 24h, tutti gli episodi. Gruppi = blocchi da 120 giorni (i parossismi vicini stanno insieme).
    yA = kept["label"].values
    gA = ((kept.index - pd.Timestamp(START)).days // 120).values
    # Modello B: 7 giorni prima dell'inizio di una fase (positivi) vs giorni di quiete (>=60 gg da eruzioni)
    onset_arr = onsets.values.astype("datetime64[D]")
    alld = data.index.values.astype("datetime64[D]")
    yB_all = np.array([((onset_arr > d) & (onset_arr <= d + 7)).any() for d in alld]).astype(int)
    quiet = (data["label"].values == 0) & data["keep"].values
    selB = (yB_all == 1) | quiet
    XB, yB2 = data.loc[selB, feats], yB_all[selB]
    gB = ((data.index[selB] - pd.Timestamp(START)).days // 120).values
    for name, (Xs, ys, gs, lab) in {"A: 24h (tutti gli episodi)": (X, yA, gA, "24h"),
                                     "B: 7gg prima di inizio fase": (XB, yB2, gB, "7gg")}.items():
        for mname, factory in mk.items():
            oof, ok = cv_eval(Xs, ys, gs, factory)
            if ok.sum() == 0 or len(np.unique(ys[ok])) < 2:
                continue
            auc = roc_auc_score(ys[ok], oof[ok])
            ap = average_precision_score(ys[ok], oof[ok])
            null = perm_null_auc(oof, ys, gs, ok)
            results.append({"modello": name, "algoritmo": mname, "n": int(ok.sum()),
                            "positivi": int(ys[ok].sum()), "AUC": auc, "AP": ap,
                            "AP_baseline": ys[ok].mean(),
                            "AUC_null_media": null.mean(), "p_perm": (1 + (null >= auc).sum()) / (len(null) + 1)})
    # importanza: AUC univariata per fase B (segno dell'effetto)
    uni = []
    for c in feats:
        a = XB.loc[yB2 == 1, c].dropna(); b = XB.loc[yB2 == 0, c].dropna()
        if len(a) and len(b):
            u = (a.values[:, None] > b.values[None, :]).mean() + 0.5 * (a.values[:, None] == b.values[None, :]).mean()
            uni.append({"feature": c, "AUC_univariata_B": u})
    return pd.DataFrame(results), pd.DataFrame(uni).sort_values("AUC_univariata_B")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    conn = get_connection()
    try:
        eq = load_earthquakes(conn)
        eruptions = load_eruption_dates(conn)
        mc = estimate_mc(eq.loc[eq["event_time"] >= pd.Timestamp(START, tz="UTC"), "magnitude"])
        last = eq["event_time"].max().tz_convert("UTC").tz_localize(None).normalize()
        end = last
        daily = daily_metrics(eq, mc, START, end)
        onsets = phase_onsets(eruptions, START, end)
        print(f"Mc={mc}  periodo {START} -> {end.date()}  fasi eruttive (onset): {len(onsets)}")
        print("Onset:", ", ".join(d.strftime("%Y-%m-%d") for d in onsets))

        res, pool = epoch_tests(daily, onsets, eruptions, START, end)
        res.to_csv(f"{OUT}/epoch_tests.csv", index=False)
        print("\n== Epoch sovrapposte (media pre-onset vs controlli) ==")
        print(res.sort_values("p_value").head(12).round(4).to_string(index=False))
        for m in ("n_mc", "log10_energy"):
            plot_epoch(daily, onsets, pool, m, f"{OUT}/epoch_{m}.png", mc)

        data = models(conn, mc, onsets)
        mres, uni = run_models(data, None, onsets)
        mres.to_csv(f"{OUT}/models.csv", index=False)
        uni.to_csv(f"{OUT}/univariate_B.csv", index=False)
        print("\n== Modelli (CV a blocchi, null da permutazione) ==")
        print(mres.round(3).to_string(index=False))
        print("\n== AUC univariata, 7gg pre-fase vs quiete ==")
        print(uni.round(3).to_string(index=False))
    finally:
        conn.close()
