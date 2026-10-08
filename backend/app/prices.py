"""Market prices via Yahoo Finance (yfinance) — current and historical closes.

Yahoo's realtime quote endpoint is unreliable from some networks (it returns
None), so we use the most recent CLOSE from a short history window as the
"current" price. It is slightly delayed but robust, and plenty accurate for a
personal tracker. Symbols are Yahoo tickers:
    'VWCE.MI'  (Borsa Italiana — .MI suffix)
    'AAPL'     (US, no suffix)
    'BTC-EUR'  (crypto pair)

A DATED close is a different question from "what is it worth now", and this
module keeps them apart. What a position is worth takes the last day that has a
close; a sum fixed on a day takes THAT day's close or waits for it, because a
purchase priced at a neighbour's close is dated on a day it did not happen and
the debit it fixes is never restated. `_close_on` holds that policy, including
when waiting ends.

OpenFIGI maps an ISIN to a ticker, but not reliably to the exact Yahoo symbol
(exchange suffix), so resolve_isin() returns *suggestions* for the user to pick.

All network calls live in `_fetch_*` helpers so tests can monkeypatch them and
never hit the network.
"""

from __future__ import annotations

import datetime
import logging
import math
import re
from dataclasses import dataclass

from app import dated

logger = logging.getLogger(__name__)

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"

# How far back "the latest close" is willing to look for a day that has one.
_RECENT_DAYS = 10

# How far past the asked day the dated window reaches, when today is further
# off still: enough calendar days to contain the ended sessions below even
# across a holiday week, and no more — the rows after them decide nothing.
_CLOSE_LOOK_AHEAD = 21

# How many ended sessions must publish a close of their own before a weekday
# that has none is taken as a day the market did not trade. A policy, not a
# measurement; `_close_on` says what it sits between and why, and why a
# weekend does not wait for it.
CLOSES_SETTLE_WITHIN = 3


class PriceError(Exception):
    """Raised when a price or mapping cannot be fetched."""


class MarketUnreachable(PriceError):
    """Nothing answered — which says nothing at all about the symbol.

    A subclass so every existing `except PriceError` keeps working; callers
    that care about the difference can now ask for it."""


class NoCloseYet(PriceError):
    """That day has no close, and it is too early to say it never will.

    Not an outage and not a bad ticker: the market answered, and what it has
    for that day is a row with no prices in it, or no row. A sum fixed on a day
    waits for that day's own close rather than taking a neighbour's — see
    `_close_on` for when the waiting ends."""


# A symbol that is always quoted, used to tell "your ticker is wrong" apart
# from "nobody answered". Two of them, because the point of a canary is to be
# more reliable than the thing it is testing.
_CANARIES = ("AAPL", "MSFT")
_REACHABLE_TTL = 20  # seconds; a burst of failures must not fire a burst of probes
_reachable_at: float | None = None
_reachable_was: bool = True


def _fetch_probe(symbol: str) -> bool:
    """True if the market answers for a symbol known to exist. Network call."""
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period="5d")
    return hist is not None and len(hist) > 0


def _reset_reachability() -> None:
    """Forget the cached verdict (tests, and after a deliberate retry)."""
    global _reachable_at, _reachable_was
    _reachable_at, _reachable_was = None, True


def market_reachable() -> bool:
    """Is the market answering at all right now?

    Asked only after something has already failed, and cached briefly, so the
    cost is one extra call per outage rather than one per symbol. It is the
    lightbulb test: if another lamp works, the bulb is dead; if nothing works,
    the power is out."""
    global _reachable_at, _reachable_was
    import time

    now = time.monotonic()
    if _reachable_at is not None and (now - _reachable_at) < _REACHABLE_TTL:
        return _reachable_was
    verdict = False
    for canary in _CANARIES:
        try:
            if _fetch_probe(canary):
                verdict = True
                break
        except Exception:
            continue
    _reachable_at, _reachable_was = now, verdict
    return verdict


def _no_data(symbol: str, when: str = "") -> PriceError:
    """The right exception for an empty result, which has two causes.

    Blaming the ticker when the network is down is not a cosmetic slip: it
    tells someone to change a symbol that was correct, and they will."""
    if not market_reachable():
        return MarketUnreachable(
            f"Could not reach the market{when}, so '{symbol}' may well be correct. "
            "Nothing answered, so this says nothing about the symbol."
        )
    return PriceError(f"No price data for '{symbol}'{when} (check the ticker/suffix)")


def _fetch_close_window(
    symbol: str, start: datetime.date, end: datetime.date
) -> list[tuple[str, float | None]]:
    """[(day_iso, close or None), ...] for every row Yahoo has in [start, end),
    ascending, rows with no prices INCLUDED as None. Network call.

    `keepna=True` is the whole point of this helper, and a line in this
    module that must not be simplified. yfinance drops a row whose prices are
    all NaN and whose volume is zero, and the volume Yahoo reports for the most
    recent bar is not always zero — measured on 2026-09-17 for VWCE.MI's 16th:
    volume 16,407 in a window ending that day (the row survives, with a NaN
    close) and 0 in a wider one (the row is dropped). So the same missing close
    comes back as a NaN row or as no row at all depending on where the window
    ends, and a caller reading "the last row" silently gets the PREVIOUS
    session — priced and dated on a day the purchase did not happen. Asking for
    the rows as they are lets the day being asked about be looked up instead of
    assumed.

    `auto_adjust=False` must not be simplified either. yfinance's default
    puts Yahoo's dividend-adjusted close where the close is: lower than the
    price the day traded at by every dividend paid since, and a purchase is
    made at the price of its day. Measured 2026-10-08 (brief AK), each on the
    session before an ex-date: `get_price_on` read KO's 2026-09-14 as 88.82
    where the close was 89.35, ENI.MI's 2026-09-18 as 23.68 for 23.95, and
    ISF.L's 2026-09-16 as 1046.1134 for 1046.20. So a plan's occurrence priced
    after an ex-date of its fund had passed was bought below its day's price."""
    import yfinance as yf

    hist = yf.Ticker(symbol).history(
        start=start.isoformat(), end=end.isoformat(), keepna=True, auto_adjust=False
    )
    if hist is None or len(hist) == 0:
        return []
    out: list[tuple[str, float | None]] = []
    for idx, close in hist["Close"].items():
        value = float(close)
        out.append((idx.date().isoformat(), None if value != value else value))  # NaN
    return sorted(out)


def _fetch_recent_close(symbol: str) -> tuple[float, str | None, str]:
    """(price, currency, as_of_iso) from the latest close. Network call.

    "The latest close" is the last day that HAS one: for what a position is
    worth now — as opposed to a sum fixed on a day — the previous real close is
    the right answer, and a session whose prices never arrived must simply be
    stepped over. It used to take the last row whatever was in it, so on a day
    like VWCE.MI's 2026-09-16 a NaN travelled into the price cache and into
    every holding refreshed from it.

    The currency is None when Yahoo does not say it. It used to default to EUR,
    which was a guess that happened to be the base; a listing whose currency is
    not known is now left unknown, and nothing converts it as if it were."""
    today = datetime.date.fromisoformat(dated.today())
    rows = _fetch_close_window(
        symbol, today - datetime.timedelta(days=_RECENT_DAYS), today + datetime.timedelta(days=1)
    )
    priced = [(day, close) for day, close in rows if close is not None]
    if not priced:
        raise _no_data(symbol)
    as_of, close = priced[-1]
    currency = None
    try:
        currency = _fetch_currency(symbol)
    except Exception:
        pass
    return close, currency, as_of


# The two days a weekend has, by `weekday() - 5`, named here rather than by
# strftime, which names them in whatever locale the process runs in.
_WEEKEND = ("Saturday", "Sunday")


def _trades_on_weekends(rows: list[tuple[str, float | None]]) -> bool:
    """Whether any of Yahoo's rows falls on a Saturday or a Sunday, with or
    without a close: a symbol that has weekend sessions at all (a coin), as
    told by its own data rather than by a calendar or a class."""
    return any(datetime.date.fromisoformat(day).weekday() >= 5 for day, _ in rows)


def _close_on(symbol: str, on: datetime.date, today: datetime.date) -> tuple[float, str]:
    """(price, as_of_iso) for a sum fixed on `on`: that day's own close, or —
    once the market has moved on without ever publishing it — the first ENDED
    session after it. Raises `NoCloseYet` while the answer is still "wait".

    This is the policy, and it is the reason this function exists instead of a
    line reading "the last close on or before".

    **A day's own close, or nothing.** A purchase priced at a neighbouring
    day's close, and dated that day, is a purchase on a day it did not happen —
    and the debit it fixes, at that day's exchange rate, is never restated.

    **Only an ENDED session is evidence.** Today's row is today's session,
    which may still be trading: on 2026-09-17 at 10:06 in Milan, VWCE.MI's 16th
    was empty and its 17th was there, at a price that moved all day and settled
    at 167.64 around 18:00. Reading that row as "the market has moved on" buys
    the 16th at an intraday price of the 17th, which is not a close at all.

    **Three ended sessions, then it is a day that did not trade.** A close is
    sometimes merely late — ENI.MI's 16th was empty at 10:06 and there by 11:55
    the next morning, before any later session had ended — and sometimes it
    never comes: VWCE.MI has no close for 2025-10-24 or 2026-03-06, months
    later, and none for 2026-09-16 with the 17th already closed. Nothing in the
    row tells the two apart, so the only evidence is what came after it. Three
    is a policy rather than a measurement: it sits above the late closes that
    were observed (which arrived before a single session had ended) and far
    below the gaps that never filled.

    A day the market was closed is the same case and takes the same answer: the
    first ended session after it. A holiday leaves no row at all (measured over
    two years on VWCE.MI, VWCE.DE, ENI.MI and VTI: no row for any of eight
    exchange holidays), but so does a row Yahoo has not written yet, and
    nothing distinguishes them on the day, so a weekday without a close waits.

    **A weekend is not a missing close** (the reader's decision, brief AJ,
    2026-10-08). The same measurement found no row for any weekend, and the
    wait cost every occurrence that fell on one three sessions of patience for
    a close no market could have: a plan's Sunday was bought on Thursday, at
    Monday's close, and the chat meanwhile said the plan had not run. So a
    Saturday or a Sunday with no close takes the first ended session after it
    at once, for a symbol that has no row on any weekend day of the window;
    the window reaches a week before the day asked, so it always holds a
    weekend. A symbol that trades on weekends has rows there (on 2026-10-08,
    8 of ETH-EUR's 31 rows in a month were weekend days, and 0 of six
    exchange listings'), and its Saturday waits for its own close as any day
    does: concluding from that absence would buy a coin's Saturday at
    Sunday's close, the trap brief R named."""
    window_end = min(
        today, on + datetime.timedelta(days=_CLOSE_LOOK_AHEAD)
    ) + datetime.timedelta(days=1)
    rows = _fetch_close_window(symbol, on - datetime.timedelta(days=7), window_end)
    if not rows:
        raise _no_data(symbol, f" near {on.isoformat()}")
    asked, now = on.isoformat(), today.isoformat()
    for day, close in rows:
        if day == asked and close is not None:
            return close, day
    ended = [(day, close) for day, close in rows if asked < day < now and close is not None]
    if on.weekday() >= 5 and not _trades_on_weekends(rows):
        if ended:
            return ended[0][1], ended[0][0]
        raise NoCloseYet(
            f"{asked} is a {_WEEKEND[on.weekday() - 5]}, when '{symbol}' does not trade: "
            "it takes the close of the first session after it, which has not ended yet."
        )
    if not ended:
        raise NoCloseYet(
            f"The market has no close for '{symbol}' on {asked} yet, and no session "
            "after it has ended either. A purchase fixed on a day waits for that "
            "day's close; nothing is recorded until it has one."
        )
    if len(ended) < CLOSES_SETTLE_WITHIN:
        since = ", ".join(day for day, _ in ended)
        raise NoCloseYet(
            f"The market has no close for '{symbol}' on {asked}: {len(ended)} session(s) "
            f"have ended since ({since}) and it still has none. After "
            f"{CLOSES_SETTLE_WITHIN} it is taken as a day '{symbol}' did not trade, and "
            "the first session after it is used."
        )
    return ended[0][1], ended[0][0]


def _fetch_name(symbol: str) -> str | None:
    """The instrument's own name, as the exchange knows it. Network call."""
    import yfinance as yf

    info = yf.Ticker(symbol).get_info() or {}
    return info.get("longName") or info.get("shortName") or None


# Crypto trades as a PAIR: "Bitcoin" is not a Yahoo symbol and never will be,
# because a coin has no price until you say "priced in what". People type the
# name they know, so accept it and resolve it — then SHOW what it resolved to,
# rather than translating behind their back.
#
# Bare three-letter codes are only mapped where no meaningful listed equity
# uses them. LINK, MATIC, DOT and friends are deliberately reachable by full
# name only: a silent alias that steals a stock ticker is exactly the class of
# error this project keeps having to undo.
_CRYPTO_ALIASES = {
    "bitcoin": "BTC", "btc": "BTC", "xbt": "BTC",
    "ethereum": "ETH", "ether": "ETH", "eth": "ETH",
    "ripple": "XRP", "xrp": "XRP",
    "dogecoin": "DOGE", "doge": "DOGE",
    "litecoin": "LTC",
    "cardano": "ADA",
    "solana": "SOL",
    "polkadot": "DOT",
    "avalanche": "AVAX",
    "chainlink": "LINK",
    "polygon": "POL",
    "tether": "USDT",
    "monero": "XMR",
    "stellar": "XLM",
    "bitcoincash": "BCH",
}


def resolve_symbol(text: str, base_currency: str) -> str:
    """A user-typed instrument name -> the Yahoo symbol that prices it.

    Anything already shaped like a symbol is returned untouched: a pair
    ('BTC-EUR'), a suffixed listing ('VWCE.MI') or a plain ticker all pass
    through, so this can never hijack an equity. Only a bare crypto NAME is
    rewritten, and into the base currency — which the caller reads from its
    session and passes in: this module has no database to ask."""
    raw = (text or "").strip()
    if not raw or "-" in raw or "." in raw:
        return raw
    coin = _CRYPTO_ALIASES.get(raw.lower().replace(" ", ""))
    if not coin:
        return raw
    return f"{coin}-{base_currency.strip().upper()}"


def _usd_pair(symbol: str) -> str | None:
    """The same coin quoted in dollars, or None if this is not a crypto pair."""
    coin, _, quote = symbol.partition("-")
    if not quote or quote.upper() == "USD":
        return None
    return f"{coin}-USD" if coin.upper() in set(_CRYPTO_ALIASES.values()) else None


def get_quote(symbol: str, base_currency: str) -> dict:
    """Latest available price for a Yahoo symbol, WITH the instrument's name.

    The name is the point. A ticker that resolves to a plausible price for the
    wrong fund is invisible — MVOL.MI returns a perfectly good 67 EUR for the
    *World* minimum-volatility ETF when you hold the *EM* one, and nothing on
    screen says so. Showing what the ticker resolved to turns a silent
    mis-entry into something you catch in a second. It is best-effort: a
    missing name must never withhold a price."""
    symbol = resolve_symbol(symbol, base_currency)
    if not symbol:
        raise PriceError("Empty symbol")
    try:
        price, currency, as_of = _fetch_recent_close(symbol)
    except MarketUnreachable:
        raise  # nothing answered; trying a second pair would just fail again
    except PriceError:
        # A coin Yahoo does not quote in the base currency is still quoted in
        # dollars; the FX layer converts it. Better a priced position in the
        # wrong currency than an unpriced one.
        alt = _usd_pair(symbol)
        if alt is None:
            raise
        price, currency, as_of = _fetch_recent_close(alt)
        symbol = alt
    name = None
    try:
        name = _fetch_name(symbol)
    except Exception:
        pass
    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 4),
        "currency": currency,
        "as_of": as_of,
    }


def _fetch_recent_closes(symbols: list[str]) -> dict[str, tuple[float, str]]:
    """{symbol: (price, as_of_iso)} for the latest close of each symbol, in one
    batch. Symbols with no data are simply absent from the result. Network
    call.

    One batch, not one request: yfinance asks Yahoo once a symbol and runs the
    requests in threads, so the batch takes about as long as its slowest
    symbol. Measured 2026-10-08 (brief AK): 18 symbols, 18 chart requests,
    1.24 s and 30,265 bytes, where the catch-up's 18 dividend windows, asked one
    after another, took 4.63 s. This said ONE request until then.

    The close, not Yahoo's dividend-adjusted one (`auto_adjust=False`, see
    `_fetch_close_window`). The two gave the same last close on all 18 that
    day; the adjusted one is lower for any day a dividend has gone ex since."""
    import yfinance as yf

    data = yf.download(
        tickers=" ".join(symbols),
        period="5d",
        group_by="ticker",
        progress=False,
        auto_adjust=False,
    )
    out: dict[str, tuple[float, str]] = {}
    if data is None or len(data) == 0:
        return out
    for sym in symbols:
        try:
            # Multi-ticker downloads have per-symbol column groups; a
            # single-ticker download may return a flat frame.
            frame = data[sym] if sym in getattr(data.columns, "levels", [[]])[0] else data
            closes = frame["Close"].dropna()
            if len(closes) == 0:
                continue
            out[sym] = (float(closes.iloc[-1]), closes.index[-1].date().isoformat())
        except Exception:
            continue  # one bad symbol must not break the batch
    return out


def get_quotes(symbols: list[str]) -> dict[str, dict]:
    """Latest available prices for many Yahoo symbols in one batch
    (`_fetch_recent_closes`): {symbol: {"symbol", "price", "as_of"}}. Symbols
    that could not be priced are absent from the dict rather than raising."""
    wanted = sorted({s.strip() for s in symbols if s and s.strip()})
    if not wanted:
        return {}
    try:
        closes = _fetch_recent_closes(wanted)
    except Exception as exc:
        raise PriceError(f"Batch price fetch failed: {exc}") from exc
    return {
        sym: {"symbol": sym, "price": round(price, 4), "as_of": as_of}
        for sym, (price, as_of) in closes.items()
    }


def _fetch_currency(symbol: str) -> str | None:
    """The listing's trading currency as Yahoo spells it, or None when Yahoo
    names no three-letter code. Network call.

    As Yahoo spells it, because the case is the unit: London quotes some
    listings in pence, "GBp", and others in pounds, "GBP" (`fx._MINOR_EXACT`),
    and a dividend Yahoo names is read the same way (`_read_dividend`). This
    upper-cased it until brief AK: measured 2026-10-08, Yahoo names VOD.L and
    ISF.L "GBp" and this returned "GBP" for both, so a pence listing whose
    currency the cache learnt here would be converted as pounds."""
    import yfinance as yf

    fast = yf.Ticker(symbol).fast_info
    cur = fast.get("currency") if hasattr(fast, "get") else getattr(fast, "currency", None)
    if isinstance(cur, str) and _CURRENCY_CODE.fullmatch(cur.strip()):
        return cur.strip()
    return None


def get_currencies(symbols: list[str]) -> dict[str, str]:
    """{symbol: currency} for the symbols Yahoo knows; symbols that fail are
    simply absent. One request per symbol, so callers should only ask for
    symbols whose currency is not already cached (it never changes)."""
    out: dict[str, str] = {}
    for sym in symbols:
        try:
            cur = _fetch_currency(sym)
        except Exception:
            continue  # one bad symbol must not break the rest
        if cur:
            out[sym] = cur
    return out


def get_price_on(symbol: str, on: datetime.date, today: datetime.date | None = None) -> dict:
    """Price of a symbol on a given day — see `_close_on` for what happens when
    that day has no close, which is a policy and not a detail.

    `today` is the day the question is asked on, because "has a session ended
    since?" cannot be answered without it. It defaults to the reader's own
    clock through `dated.today()`, the app's one spelling of today, and callers
    that already hold it pass it in rather than reading the clock twice."""
    symbol = (symbol or "").strip()
    if not symbol:
        raise PriceError("Empty symbol")
    if today is None:
        today = datetime.date.fromisoformat(dated.today())
    price, as_of = _close_on(symbol, on, today)
    return {"symbol": symbol, "price": round(price, 4), "as_of": as_of}


# Yahoo answers a dividend history by range, and yfinance keeps a dividend's
# currency only through one (`Ticker.get_dividends(period)`, which `.dividends`
# is with "max"): `history()` drops that column before it returns, by range or
# by dates (see `_fetch_dividends`). Each range, with the fewest days it is sure
# to reach back.
_DIVIDEND_RANGES = (
    ("1mo", 28), ("3mo", 89), ("6mo", 181), ("1y", 365), ("2y", 730), ("5y", 1826), ("10y", 3652),
)

# How far before the day it is asked for a window must reach. The catch-up
# cuts strictly after a situation's date; a week covers a dividend stamped
# across midnight UTC (an exchange east of it) and Yahoo's clock against the
# reader's. Measured 2026-10-05 with it, on 26 tickers from Sydney to New York:
# in 460 checks, every dividend the whole history lists after the day was in
# the window.
_DIVIDEND_REACH_MARGIN = 7

_CURRENCY_CODE = re.compile(r"[A-Za-z]{3}")


def _dividend_range(since: datetime.date, today: datetime.date) -> str:
    """Yahoo's smallest range whose daily rows reach `_DIVIDEND_REACH_MARGIN`
    days before `since`; "max", the whole history, when none does.

    The whole history is what `.dividends` asks for: every daily price the
    ticker ever had, to read a few events. For the 22 tickers the reader's
    shares added, 14,363,983 bytes and 44.7 s in sequence; the "1mo" a
    situation three days old needs, 73,933 bytes and 38.5 s (measured
    2026-10-05). The time is Yahoo's: a 1.2 KB answer takes about a second."""
    needed = (today - since).days + _DIVIDEND_REACH_MARGIN
    for name, days in _DIVIDEND_RANGES:
        if needed <= days:
            return name
    return "max"


def _read_dividend(day: str, amount, named) -> dict | None:
    """One event of Yahoo's answer, read on its own: {"date", "dps"}, with
    "currency" when Yahoo names one; {"date", "unreadable"} when it cannot be
    read; None when it is no dividend (an amount of zero, dropped as it always
    was).

    A currency left unnamed is the listing's. Measured 2026-10-05: no real
    listing named one (52 tickers, Vietnam included, the case yfinance's own
    comment names), and the amounts are converted into the listing's currency:
    the Vanguard All-World fund pays in dollars, and its dividend of 2026-09-17
    in dollars (VWRD.L) over the same in euros (VWRL.MI) is 1.1486, the ECB's
    EUR/USD that day 1.1481. A named one is kept as written, case included,
    because GBp is pence and GBP pounds."""
    try:
        dps = float(amount)
    except (TypeError, ValueError):
        dps = math.nan
    if not math.isfinite(dps):
        return {"date": day, "unreadable": f"its amount {amount!r} is not a number"}
    if dps <= 0:
        return None
    if named is None or (isinstance(named, float) and math.isnan(named)):
        return {"date": day, "dps": dps}
    if isinstance(named, str) and not named.strip():
        return {"date": day, "dps": dps}
    if isinstance(named, str) and _CURRENCY_CODE.fullmatch(named.strip()):
        return {"date": day, "dps": dps, "currency": named.strip()}
    return {"date": day, "unreadable": f"its currency {named!r} is not a currency code"}


@dataclass(frozen=True)
class DividendWindow:
    """What Yahoo answered about a ticker's dividends over one of its ranges.

    `answered` says whether anything came back at all. yfinance does not raise
    when nothing does: it logs and leaves the dividends as None (measured
    2026-09-30 with the network refused), and a check nobody answered must
    never be kept as "this ticker pays nothing". `dividends` are the events of
    the range, ascending, each as `_read_dividend` reads it: none when Yahoo
    answered and lists none, and none when it did not answer.

    It carries no price. Brief AJ took the last close and the listing's
    currency from the same answer by reading yfinance's internals; through its
    public calls one request gives the dividends exactly or the dividends with
    a close, not both (brief AK, see `_fetch_dividends`). So a followed
    ticker's price is the batch's, like every other symbol's
    (`pac.refresh_prices`)."""

    answered: bool
    dividends: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        # A tuple whatever was passed, so an answer cannot grow once read; and
        # an answer that never came lists nothing.
        object.__setattr__(self, "dividends", tuple(self.dividends))
        if self.dividends and not self.answered:
            raise ValueError("an answer that never came lists no dividends")


def _fetch_dividends(symbol: str, period: str = "max") -> DividendWindow:
    """Every dividend Yahoo lists for a symbol within `period`, one of its
    ranges ("max" for the whole history), ascending, each read on its own by
    `_read_dividend`, and whether Yahoo answered at all. Network call.

    yfinance does not raise when no answer comes back: it logs the failure and
    leaves the dividends as None, where an answer with no dividend is an empty
    Series. Measured 2026-09-30 on yfinance 1.4.1 with the network refused, for
    tickers whose timezone it had cached (any ticker priced before). This
    returned [] for both, so an outage read as a fund that pays nothing, and a
    check that never happened could have been kept as the day's.

    And yfinance keeps a dividend's currency as a second column whenever any
    event names one, so the answer is then a DataFrame (shown 2026-09-30 with
    Yahoo's answer faked). It was iterated as (column, Series) pairs and
    raised, and the ticker's whole history was one skip line at every start;
    each row is now read on its own, and one that cannot be read takes nothing
    else with it.

    `get_dividends(period)` is yfinance's public call for exactly this, one
    chart request a ticker once its time zone is known. Its public sibling
    `history(period, actions=True, auto_adjust=False)` brings the closes with
    the dividends in the same one request, and is not used: measured 2026-10-08
    on 18 public tickers (brief AK), it gave the same 1,464 dividends but one,
    KO's 0.18 of 2001-09-12, a day New York did not open, which it moved to
    the session before (an event on a day with no price row goes on the row
    before it); and it drops a currency Yahoo names (read in yfinance 1.4.1).
    An ex-date decides which units earned a dividend, the rate it is converted
    at and whether it is already recorded, so the dividends come from here and
    the price from the batch."""
    import yfinance as yf

    dividends = yf.Ticker(symbol).get_dividends(period=period)
    if dividends is None:
        return DividendWindow(answered=False)
    if len(dividends) == 0:
        return DividendWindow(answered=True)
    if hasattr(dividends, "columns"):
        amounts = dividends["Dividends"]
        named = list(dividends["currency"]) if "currency" in dividends.columns else [None] * len(dividends)
    else:
        amounts, named = dividends, [None] * len(dividends)
    events = (
        _read_dividend(idx.date().isoformat(), amount, currency)
        for idx, amount, currency in zip(amounts.index, amounts.to_list(), named)
    )
    return DividendWindow(answered=True, dividends=[event for event in events if event is not None])


def get_dividends_since(symbol: str, since: datetime.date) -> DividendWindow:
    """Yahoo's answer about `symbol`'s dividends, cut to the ex-dates strictly
    AFTER `since`, ascending, each as `_read_dividend` reads it. `since` is
    exclusive because the caller's anchor (snapshot/ledger state) already
    accounts for anything up to that day.

    Asked for the smallest of Yahoo's ranges reaching before `since`
    (`_dividend_range`); `datetime.date.min` asks for the whole history.

    An answer that never came stays one (`answered` False), which the caller
    must not read as "no dividends": see `_fetch_dividends`."""
    symbol = (symbol or "").strip()
    if not symbol:
        raise PriceError("Empty symbol")
    period = _dividend_range(since, datetime.date.fromisoformat(dated.today()))
    try:
        window = _fetch_dividends(symbol, period)
    except Exception as exc:
        raise PriceError(f"Dividend history fetch failed for '{symbol}': {exc}") from exc
    lo = since.isoformat()
    return DividendWindow(
        answered=window.answered, dividends=[row for row in window.dividends if row["date"] > lo]
    )



# How long the picker is willing to wait for Yahoo. Short on purpose: the
# catalogue lane beside it answers from SQLite in milliseconds, and a slow
# source must never be the reason a list fails to appear.
LOOKUP_TIMEOUT = 4


def _fetch_lookup(query: str, count: int) -> list[dict]:
    """Yahoo's instrument search: [{symbol, name, quote_type, exchange, price}].

    Network call. Note what it does NOT return: the CURRENCY. It gives a bare
    `regularMarketPrice`, and for the same company on two exchanges those
    numbers are in different money — a share listed in New York and in
    Frankfurt comes back once in dollars and once in euros, two numbers apart by
    the exchange rate that are the same value. So the price travels
    with its exchange and never alone, and the currency arrives from an actual
    quote once something is chosen."""
    import yfinance as yf

    frame = yf.Lookup(query, timeout=LOOKUP_TIMEOUT).get_all(count=count)
    if frame is None or len(frame) == 0:
        return []
    out: list[dict] = []
    for symbol, row in frame.iterrows():
        out.append(
            {
                "symbol": str(symbol),
                "name": _as_text(row.get("shortName")),
                "quote_type": _as_text(row.get("quoteType")),
                "exchange": _as_text(row.get("exchange")),
                "price": _as_float(row.get("regularMarketPrice")),
            }
        )
    return out


def _as_text(value) -> str | None:
    """A cell of Yahoo's frame as text, or None when it is empty. A missing
    cell is NaN in the frame, and NaN is neither None nor false: read as text
    it became the name "nan" (VOOB, 2026-10-06), which is a name nobody has."""
    if value is None or value != value:  # NaN
        return None
    return str(value).strip() or None


def _as_float(value) -> float | None:
    try:
        if value is None or value != value:  # NaN
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def lookup(query: str, count: int = 8) -> list[dict]:
    """Quotable instruments matching `query` — shares, ETFs, crypto, futures.

    This is the lane the fund catalogue cannot serve, and the only source of a
    symbol that actually prices. It is also the only one that knows a share
    trades in several places under the same name: one company on NASDAQ and on
    Frankfurt comes back as two rows in two currencies, and nothing but the
    exchange tells them apart.

    Returns [] rather than raising when nothing is found or the source is
    unreachable: the picker has a second lane, and one going quiet must never
    take the other with it."""
    query = (query or "").strip()
    if len(query) < 2:
        return []
    try:
        return _fetch_lookup(query, count)
    except Exception as exc:
        logger.info("Instrument lookup failed for %r: %s: %s", query, type(exc).__name__, exc)
        return []


# How many candidates `listing` asks for. On 2026-10-06 every exact symbol asked
# (ENI.MI, AAPL, VOO, CSPX.L, ASML.AS, BTC-EUR) came back first, as itself;
# the rest are spare.
LISTING_CANDIDATES = 8


def listing(symbol: str) -> dict | None:
    """What Yahoo's lookup lists under exactly `symbol` (the row `lookup`
    would return for it), or None when it lists nothing under it.

    Unlike `lookup`, a silence is not an empty list here: it raises
    MarketUnreachable. The caller is a card for a share, which has to tell "not
    listed" from "not answered" (the second says nothing about whether the
    share exists), and yfinance raises on every failure it meets and returns
    an empty table only when nothing matched (read in yfinance 1.4.1's
    `Lookup._fetch_lookup`). Network call."""
    wanted = (symbol or "").strip().upper()
    if not wanted:
        return None
    try:
        found = _fetch_lookup(wanted, LISTING_CANDIDATES)
    except Exception as exc:
        raise MarketUnreachable(
            f"Yahoo did not answer a lookup of {wanted!r} ({type(exc).__name__})"
        ) from exc
    return next((row for row in found if row["symbol"].upper() == wanted), None)

def _fetch_openfigi(isin: str) -> list[dict]:
    """Raw OpenFIGI mapping response data for an ISIN. Network call."""
    import httpx

    resp = httpx.post(OPENFIGI_URL, json=[{"idType": "ID_ISIN", "idValue": isin}], timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    items: list[dict] = []
    for block in payload:
        for item in block.get("data", []) or []:
            items.append(item)
    return items


def resolve_isin(isin: str) -> list[dict]:
    """Best-effort ISIN -> ticker suggestions (the user picks the right listing
    and may need to add a Yahoo exchange suffix, e.g. '.MI')."""
    isin = (isin or "").strip().upper()
    if not isin:
        return []
    try:
        items = _fetch_openfigi(isin)
    except Exception as exc:
        raise PriceError(f"OpenFIGI lookup failed: {exc}") from exc
    seen: set = set()
    out: list[dict] = []
    for it in items:
        key = (it.get("ticker"), it.get("exchCode"))
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "ticker": it.get("ticker"),
                "name": it.get("name"),
                "exchange": it.get("exchCode"),
                "type": it.get("securityType"),
            }
        )
    return out
