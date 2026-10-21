"""The look-through takes a fund's ISIN from the stored catalogue before it
downloads justETF's screener.

Brief AB, 2026-10-04: `composition._resolve_isin` turned a ticker into an ISIN
by downloading justETF's whole screener (6.2 MB that day), the same file the
stored catalogue is (`catalogue`, `instruments.base_ticker` and `isin`).
Measured at `c61e5bc` (brief BE): with an invented fund in the stored
catalogue, the screener was asked anyway, and with the screener failing the
look-through answered "No ISIN found ... Add the fund's ISIN to this holding"
for a fund the app knew. Now the stored catalogue answers first; the screener
is asked only while the stored catalogue holds no fund; a ticker it gives to
several funds is asked of Trackinsight. Every fund here is invented.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app import composition
from app.database import SessionLocal

THE_FUND = "ZZ0000000017"
ISSUER_FILE = {
    "name": "Invented World UCITS ETF",
    "countries": [{"name": "United States", "pct": 70.0}, {"name": "Japan", "pct": 30.0}],
    "sectors": [{"name": "Industrials", "pct": 60.0}, {"name": "Financials", "pct": 40.0}],
    "top_holdings": [{"name": "Holding A", "pct": 5.0, "isin": None}],
    "holdings_count": 900,
}


def _catalogue(*rows: tuple[str, str]) -> None:
    """Funds in the stored catalogue, as (ISIN, base ticker)."""
    with SessionLocal() as db:
        for isin, ticker in rows:
            db.execute(text(
                "INSERT INTO instruments (isin, name, family_key, base_ticker, source, fetched_at)"
                " VALUES (:isin, :name, :family, :ticker, 'justetf', '2026-10-21T08:00:00+00:00')"
            ), {"isin": isin, "name": f"Invented fund {isin}", "family": f"invented {isin}", "ticker": ticker})
        db.commit()


@pytest.fixture()
def sources(monkeypatch) -> dict[str, list]:
    """The issuer answers for THE_FUND only; justETF's screener and
    Trackinsight's ISIN lookup record each ask."""
    asked: dict[str, list] = {"screener": [], "trackinsight": [], "issuer": []}

    def screener():
        asked["screener"].append(1)
        raise RuntimeError("justETF did not answer")

    def trackinsight_isin(ticker):
        asked["trackinsight"].append(ticker)
        return None

    def issuer(isin):
        asked["issuer"].append(isin)
        if isin != THE_FUND:
            raise RuntimeError("no adapter for it")
        return dict(ISSUER_FILE)

    monkeypatch.setattr(composition, "_fetch_equity_profile", lambda symbol: None)
    monkeypatch.setattr(composition, "_justetf_catalogue", screener)
    monkeypatch.setattr(composition, "_fetch_trackinsight_isin", trackinsight_isin)
    monkeypatch.setattr(composition, "_fetch_issuer", issuer)
    return asked


def test_a_fund_the_stored_catalogue_knows_is_looked_through_with_no_download(client, sources):
    _catalogue((THE_FUND, "ZZFND"))

    with SessionLocal() as db:
        got = composition.get_composition(db, "ZZFND.MI")

    assert (got["source"], got["isin"]) == ("issuer", THE_FUND)
    assert sources["screener"] == [], "the screener's own file is the stored catalogue"
    assert not any("Add the fund's ISIN" in e for e in got["errors"])


def test_a_stored_catalogue_that_holds_no_fund_asks_the_screener_as_before(client, sources, monkeypatch):
    monkeypatch.setattr(composition, "_justetf_catalogue", lambda: sources["screener"].append(1) or {"ZZFND": THE_FUND})

    with SessionLocal() as db:
        got = composition.get_composition(db, "ZZFND.MI")

    assert (got["source"], got["isin"]) == ("issuer", THE_FUND)
    assert sources["screener"] == [1]


def test_a_ticker_the_catalogue_gives_two_funds_is_asked_of_trackinsight(client, sources):
    _catalogue(("ZZ0000000025", "ZZTWO"), ("ZZ0000000033", "ZZTWO"))

    with SessionLocal() as db, pytest.raises(composition.Undecomposable) as caught:
        composition.get_composition(db, "ZZTWO.MI")

    assert sources["screener"] == []
    assert sources["trackinsight"] == ["ZZTWO"]
    assert sources["issuer"] == [], "no ISIN taken from a guess between two funds"
    assert any("Add the fund's ISIN" in e for e in caught.value.errors), "no source found one"
