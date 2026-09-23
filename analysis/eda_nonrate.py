"""
Analisi esplorativa con feature NON legate al tasso (features/nonrate.py).

1. Epoch sovrapposte: valore della feature il giorno prima dell'inizio di ciascuna fase eruttiva
   vs date di controllo in quiete (stesso schema di eda_preeruptive). Due versioni: valore grezzo
   e valore "detrendato" (meno la mediana mobile annuale della feature), per neutralizzare derive
   lente del catalogo. Correzione di Holm su tutti i test.
2. Modelli A (24h) e B (7gg prima di un onset) con feature: solo tasso, solo non-tasso, combinate.

Esecuzione: python -m analysis.eda_nonrate     (output in reports/)
"""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from analysis.eda_preeruptive import (OUT, START, N_NULL, RNG, cv_eval, holm, perm_null_auc,
                                      phase_onsets, run_models)  # noqa: F401
from analysis.eda_preeruptive import models as rate_dataset
from db.connection import get_connection
from features.build_dataset import estimate_mc, load_earthquakes, load_eruption_dates
from features.nonrate import build_nonrate_features
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def epoch_tests_nonrate(F: pd.DataFrame, onsets, eruptions):
    er = eruptions.values.astype("datetime64[D]")
    days = F.index
    dv = days.values.astype("datetime64[D]")
    ok = np.array([not ((er >= d - 30) & (er <= d + 30)).any() for d in dv])
    pool_idx = days[ok]
    detr = F - F.rolling(365, center=True, min_periods=120).median()
    rows = []
    for version, D in (("grezzo", F), ("detrendato", detr)):
        for c in F.columns:
            pool = D.loc[pool_idx, c].dropna().values
            obs_vals = D[c].reindex(onsets - pd.Timedelta(days=1)).dropna().values
            if len(obs_vals) < 8 or len(pool) < 50:
                continue
            obs = obs_vals.mean()
            null = np.array([RNG.choice(pool, size=len(obs_vals)).mean() for _ in range(N_NULL)])
            p = (1 + np.sum(np.abs(null - null.mean()) >= abs(obs - null.mean()))) / (N_NULL + 1)
            rows.append({"feature": c, "versione": version, "n_onset": len(obs_vals),
                         "media_pre_onset": obs, "media_controlli": null.mean(),
                         "percentile_null": (null < obs).mean() * 100, "p_value": p})
    res = pd.DataFrame(rows)
    res["p_holm"] = holm(res["p_value"].values)
    return res


def eval_sets(data, feature_sets, onsets):
    """Modelli A e B per ciascun insieme di feature."""
    kept = data[data["keep"]]
    gA = ((kept.index - pd.Timestamp(START)).days // 120).values
    onset_arr = onsets.values.astype("datetime64[D]")
    alld = data.index.values.astype("datetime64[D]")
    yB_all = np.array([((onset_arr > d) & (onset_arr <= d + 7)).any() for d in alld]).astype(int)
    quiet = (data["label"].values == 0) & data["keep"].values
    selB = (yB_all == 1) | quiet
    gB = ((data.index[selB] - pd.Timestamp(START)).days // 120).values
    mk = {
        "logistica": lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                           LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced")),
        "random_forest": lambda: make_pipeline(SimpleImputer(strategy="median"),
                                               RandomForestClassifier(300, min_samples_leaf=5, max_depth=4,
                                                                      class_weight="balanced_subsample",
                                                                      random_state=0, n_jobs=-1)),
    }
    rows = []
    for setname, cols in feature_sets.items():
        for task, (X, y, g) in {"A: 24h": (kept[cols], kept["label"].values, gA),
                                "B: 7gg pre-fase": (data.loc[selB, cols], yB_all[selB], gB)}.items():
            for mname, factory in mk.items():
                oof, ok = cv_eval(X, y, g, factory)
                if ok.sum() == 0 or len(np.unique(y[ok])) < 2:
                    continue
                auc = roc_auc_score(y[ok], oof[ok])
                null = perm_null_auc(oof, y, g, ok, n=200)
                rows.append({"feature_set": setname, "task": task, "algoritmo": mname,
                             "AUC": auc, "AUC_null": null.mean(), "guadagno": auc - null.mean(),
                             "p_perm": (1 + (null >= auc).sum()) / (len(null) + 1)})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    conn = get_connection()
    try:
        eq = load_earthquakes(conn)
        eruptions = load_eruption_dates(conn)
        mc = estimate_mc(eq.loc[eq["event_time"] >= pd.Timestamp(START, tz="UTC"), "magnitude"])
        end = eq["event_time"].max().tz_convert("UTC").tz_localize(None).normalize()
        days = pd.date_range(START, end - pd.Timedelta(days=1), freq="D")
        F = build_nonrate_features(eq, pd.date_range(pd.Timestamp(START) - pd.Timedelta(days=400), end - pd.Timedelta(days=1)))
        onsets = phase_onsets(eruptions, START, end)
        Fd = F.loc[days]

        res = epoch_tests_nonrate(F, onsets, eruptions)
        res.to_csv(f"{OUT}/nonrate_epoch_tests.csv", index=False)
        print(f"Test totali: {len(res)}; significativi con Holm<0.05: {(res.p_holm < 0.05).sum()}")
        print(res.sort_values("p_value").head(12).round(4).to_string(index=False))

        rate_data = rate_dataset(conn, mc, onsets)
        rate_cols = [c for c in rate_data.columns if c not in ("label", "keep")]
        data = rate_data.join(Fd, how="left")
        sets = {"solo_tasso": rate_cols, "solo_non_tasso": list(F.columns),
                "combinate": rate_cols + list(F.columns)}
        mres = eval_sets(data, sets, onsets)
        mres.to_csv(f"{OUT}/nonrate_models.csv", index=False)
        print("\n== Modelli ==")
        print(mres.round(3).to_string(index=False))
    finally:
        conn.close()
