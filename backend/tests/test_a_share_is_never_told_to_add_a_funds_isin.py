"""A share is never told to add a fund's ISIN (brief BD).

Yahoo's profile is what tells a share from a fund (`quoteType`). A share it
names with no country and no sector came back from that step as None, as if
it were a fund, so the fund sources ran and their remedy reached the page:
"Add the fund's ISIN to this holding" (probed on these fixtures, 2026-10-20).
Such a share now stops at the profile with a share's reason, and a fund keeps
its remedy. Every source is faked; nothing leaves the machine."""

from __future__ import annotations

import datetime

import pytest
import yfinance

from app import composition

# The real profile step, taken at collection, before the suite's fixtures
# fake it: its one network call, yfinance's `get_info`, each test fakes.
REAL_PROFILE = composition._fetch_equity_profile

TODAY = datetime.date.today().isoformat()


@pytest.fixture
def yahoo_says(monkeypatch):
    """Yahoo's profile answers `info`; every fund source has nothing."""

    def answer(info: dict) -> None:
        monkeypatch.setattr(composition, "_fetch_equity_profile", REAL_PROFILE)
        monkeypatch.setattr(yfinance.Ticker, "get_info", lambda self: dict(info))
        monkeypatch.setattr(composition, "_justetf_catalogue", lambda: {})
        monkeypatch.setattr(composition, "_fetch_trackinsight_isin", lambda ticker: None)

        def nothing(*args):
            raise composition.CompositionError("nothing for it")

        for name in ("_fetch_issuer", "_fetch_justetf", "_fetch_trackinsight", "_fetch_yf_sectors"):
            monkeypatch.setattr(composition, name, nothing)

    return answer


def test_a_share_yahoo_names_without_a_place_is_said_as_a_share(yahoo_says):
    yahoo_says({"quoteType": "EQUITY", "longName": "ZZ Share AG"})
    with pytest.raises(composition.Undecomposable) as caught:
        composition._resolve_and_fetch("ZZSH.DE")
    assert "ISIN" not in str(caught.value)
    assert caught.value.errors == [composition.SHARE_WITH_NO_PLACE]


def test_the_look_through_tells_the_page_it_is_a_share(client, yahoo_says):
    yahoo_says({"quoteType": "EQUITY", "longName": "ZZ Share AG"})
    iid = client.post("/api/institutions", json={"name": "Example Broker"}).json()["id"]
    sid = client.post(f"/api/institutions/{iid}/snapshots", json={"date": TODAY}).json()["id"]
    client.post(
        f"/api/snapshots/{sid}/holdings",
        json={"asset_name": "ZZ Share AG", "asset_class": "equity", "symbol": "ZZSH.DE",
              "quantity": 10, "unit_price": 50, "currency": "EUR"},
    )
    body = client.get("/api/dashboard/portfolio/composition").json()
    (row,) = [r for r in body["rows"] if r["symbol"] == "ZZSH.DE"]
    assert row["decomposed"] is False
    assert "fund's ISIN" not in row["error"]
    assert composition.SHARE_WITH_NO_PLACE in row["error"]


def test_a_share_yahoo_places_still_resolves_to_itself(yahoo_says):
    yahoo_says({"quoteType": "EQUITY", "longName": "ZZ Share AG", "country": "Germany", "sector": "Technology"})
    got = composition._resolve_and_fetch("ZZSH.DE")
    assert got["source"] == "equity"
    assert got["countries"] == [{"name": "Germany", "pct": 100.0}]


def test_a_fund_keeps_the_remedy_of_its_isin(yahoo_says):
    yahoo_says({"quoteType": "ETF", "longName": "ZZ World ETF"})
    with pytest.raises(composition.Undecomposable) as caught:
        composition._resolve_and_fetch("ZZWF.MI")
    assert "Add the fund's ISIN to this holding" in str(caught.value)
