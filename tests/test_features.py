"""Test offline della costruzione del dataset (nessun DB)."""
import numpy as np
import pandas as pd
import pytest

from features.build_dataset import b_value_aki, build_features, estimate_mc, label_days


def test_b_value_aki_recupera_b_noto():
    rng = np.random.default_rng(0)
    mc, b = 1.5, 1.0
    mags = np.round(mc - 0.05 + rng.exponential(1 / (b * np.log(10)), 20000), 1)
    assert b_value_aki(mags, mc) == pytest.approx(b, abs=0.05)


def test_b_value_aki_senza_eventi_sopra_mc():
    assert np.isnan(b_value_aki(np.array([0.5, 0.8]), 1.5))


def test_estimate_mc_massima_curvatura_piu_0_2():
    mags = pd.Series([1.0] * 5 + [1.3] * 20 + [2.0] * 3)
    assert estimate_mc(mags) == 1.5


def _eq(rows):
    return pd.DataFrame({"event_time": pd.to_datetime([r[0] for r in rows], utc=True),
                         "magnitude": [r[1] for r in rows]})


def test_build_features_non_usa_dati_futuri():
    eq = _eq([("2024-01-01 12:00", 2.0), ("2024-01-02 12:00", 3.0)])
    feats = build_features(eq, pd.DatetimeIndex(["2024-01-01"]), mc=1.5)
    assert feats.loc["2024-01-01", "n_all_7d"] == 1
    assert feats.loc["2024-01-01", "n_mc_7d"] == 1


def test_build_features_finestra_mobile():
    eq = _eq([("2024-01-01 12:00", 2.0), ("2024-01-20 12:00", 2.0)])
    feats = build_features(eq, pd.DatetimeIndex(["2024-01-21"]), mc=1.5)
    assert feats.loc["2024-01-21", "n_all_7d"] == 1
    assert feats.loc["2024-01-21", "n_all_30d"] == 2


def test_label_days_positivi_e_esclusione_negativi_vicini():
    days = pd.date_range("2024-01-01", "2024-06-01", freq="D")
    eruptions = pd.DatetimeIndex(["2024-01-10"])
    lab = label_days(days, eruptions, min_gap_days=60)
    assert lab.loc["2024-01-09", "label"] == 1
    assert lab.loc["2024-01-08", "label"] == 0 and not lab.loc["2024-01-08", "keep"]
    assert lab.loc["2024-06-01", "keep"]


def test_holm_monotono_e_limitato_a_uno():
    from analysis.eda_preeruptive import holm
    adj = holm(np.array([0.01, 0.04, 0.03]))
    assert adj[0] == pytest.approx(0.03) and adj.max() <= 1.0
    assert adj[1] >= adj[2] >= adj[0]


def test_phase_onsets_raggruppa_serie_vicine():
    from analysis.eda_preeruptive import phase_onsets
    er = pd.DatetimeIndex(["2021-01-01", "2021-01-10", "2021-03-15", "2021-03-20"])
    on = phase_onsets(er, "2021-01-01", pd.Timestamp("2021-12-31"))
    assert list(on) == [pd.Timestamp("2021-01-01"), pd.Timestamp("2021-03-15")]
