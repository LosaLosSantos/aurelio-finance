"""The ECB's rates are asked at Frankfurter's own address.

Brief AF, 2026-10-05: the app's request to `api.frankfurter.app` answered 301
to `api.frankfurter.dev/v1`, so every rate request was two, to two hosts.
Measured again on 2026-10-21 (brief BE, one free request to each address, no
key): the 301 still stands, and the two answers are byte-identical. The app
now asks the second address itself.
"""

from __future__ import annotations

import httpx

from app import fx

# The real fetch, kept before the suite's floor replaces it for every test.
_REAL_FETCH_RATES = fx._fetch_rates


class _Answer:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"rates": {"2026-10-14": {"USD": 1.16}}}


def test_a_range_of_rates_is_asked_at_frankfurter_dev(monkeypatch):
    asked: list[tuple] = []

    def get(url, params=None, timeout=None, follow_redirects=None):
        asked.append((url, params))
        return _Answer()

    monkeypatch.setattr(httpx, "get", get)

    rates = _REAL_FETCH_RATES("EUR", "2026-10-14", "2026-10-16")

    assert asked == [("https://api.frankfurter.dev/v1/2026-10-14..2026-10-16", {"base": "EUR"})]
    assert rates == {"2026-10-14": {"USD": 1.16}}
