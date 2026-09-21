"""Test offline di login(): earthaccess è sostituito da un finto, nessuna rete."""
import pytest
from earthaccess.exceptions import LoginAttemptFailure

from ingestion import earthdata_check


def _set_credentials(monkeypatch, user="u", password="p", token=""):
    monkeypatch.setattr(earthdata_check, "EARTHDATA_USERNAME", user)
    monkeypatch.setattr(earthdata_check, "EARTHDATA_PASSWORD", password)
    monkeypatch.setattr(earthdata_check, "EARTHDATA_TOKEN", token)


def test_login_senza_credenziali(monkeypatch):
    _set_credentials(monkeypatch, user="", password="")

    with pytest.raises(SystemExit, match="Credenziali Earthdata mancanti"):
        earthdata_check.login()


def test_login_rifiutato_da_earthdata(monkeypatch):
    _set_credentials(monkeypatch)

    def fake_login(strategy):
        raise LoginAttemptFailure("credenziali errate")

    monkeypatch.setattr(earthdata_check.earthaccess, "login", fake_login)

    with pytest.raises(SystemExit, match="Login Earthdata fallito"):
        earthdata_check.login()


def test_login_riuscito(monkeypatch):
    _set_credentials(monkeypatch)

    class FakeAuth:
        authenticated = True

    monkeypatch.setattr(earthdata_check.earthaccess, "login", lambda strategy: FakeAuth())

    assert earthdata_check.login().authenticated
