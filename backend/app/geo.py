"""Country -> currency and country -> region, for look-through exposure.

Why this exists: a portfolio of EUR-listed UCITS ETFs *feels* like a euro
portfolio, but its risk is wherever the underlying companies are. Mapping the
look-through country weights onto currencies and regions is what turns
"VWCE 60% United States" into "you carry ~60% USD exposure".

HONEST LIMITS, stated once here so the UI can repeat them:
- This is exposure by the company's country, not by where it earns its
  revenue. Nestlé is mapped to CHF though it sells worldwide; a US-listed
  company with mostly European sales still counts as USD.
- Currency exposure is not the same as currency risk for a hedged share class:
  a EUR-hedged ETF still holds US companies, and this map will call it USD.
  We do not model hedging.
- Names come from the composition sources (justETF / Morningstar), which use
  plain English country names; anything unknown falls into "Other" rather than
  being guessed.
"""

from __future__ import annotations

# Eurozone members share EUR; the rest carry their own currency.
_EUROZONE = {
    "Austria", "Belgium", "Croatia", "Cyprus", "Estonia", "Finland", "France",
    "Germany", "Greece", "Ireland", "Italy", "Latvia", "Lithuania",
    "Luxembourg", "Malta", "Netherlands", "Portugal", "Slovakia", "Slovenia",
    "Spain",
}

_CURRENCY_BY_COUNTRY = {
    "United States": "USD",
    "Japan": "JPY",
    "United Kingdom": "GBP",
    "Switzerland": "CHF",
    "Canada": "CAD",
    "Australia": "AUD",
    "New Zealand": "NZD",
    "China": "CNY",
    "Hong Kong": "HKD",
    "Taiwan": "TWD",
    "South Korea": "KRW",
    "India": "INR",
    "Brazil": "BRL",
    "Mexico": "MXN",
    "South Africa": "ZAR",
    "Sweden": "SEK",
    "Norway": "NOK",
    "Denmark": "DKK",
    "Poland": "PLN",
    "Czech Republic": "CZK",
    "Hungary": "HUF",
    "Israel": "ILS",
    "Singapore": "SGD",
    "Thailand": "THB",
    "Indonesia": "IDR",
    "Malaysia": "MYR",
    "Philippines": "PHP",
    "Turkey": "TRY",
    "Saudi Arabia": "SAR",
    "United Arab Emirates": "AED",
    "Chile": "CLP",
    "Colombia": "COP",
    "Peru": "PEN",
}

_REGION_BY_COUNTRY = {
    "United States": "North America",
    "Canada": "North America",
    "Mexico": "North America",
    "Japan": "Developed Asia-Pacific",
    "Australia": "Developed Asia-Pacific",
    "New Zealand": "Developed Asia-Pacific",
    "Singapore": "Developed Asia-Pacific",
    "Hong Kong": "Developed Asia-Pacific",
    "South Korea": "Developed Asia-Pacific",
    "United Kingdom": "Europe",
    "Switzerland": "Europe",
    "Sweden": "Europe",
    "Norway": "Europe",
    "Denmark": "Europe",
    "Israel": "Emerging & other",
    "China": "Emerging & other",
    "Taiwan": "Emerging & other",
    "India": "Emerging & other",
    "Brazil": "Emerging & other",
    "South Africa": "Emerging & other",
    "Thailand": "Emerging & other",
    "Indonesia": "Emerging & other",
    "Malaysia": "Emerging & other",
    "Philippines": "Emerging & other",
    "Turkey": "Emerging & other",
    "Saudi Arabia": "Emerging & other",
    "United Arab Emirates": "Emerging & other",
    "Poland": "Emerging & other",
    "Czech Republic": "Emerging & other",
    "Hungary": "Emerging & other",
    "Chile": "Emerging & other",
    "Colombia": "Emerging & other",
    "Peru": "Emerging & other",
}

UNKNOWN = "Other"

# Issuers disagree on how to name a country: iShares writes "United States",
# Vanguard sends the ISO-3166 alpha-2 code. Everything is normalised to the
# long name so the axes from different funds actually add up together.
_ISO2 = {
    "US": "United States", "JP": "Japan", "GB": "United Kingdom",
    "CH": "Switzerland", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand",
    "CN": "China", "HK": "Hong Kong", "TW": "Taiwan", "KR": "South Korea",
    "IN": "India", "BR": "Brazil", "MX": "Mexico", "ZA": "South Africa",
    "SE": "Sweden", "NO": "Norway", "DK": "Denmark", "PL": "Poland",
    "CZ": "Czech Republic", "HU": "Hungary", "IL": "Israel", "SG": "Singapore",
    "TH": "Thailand", "ID": "Indonesia", "MY": "Malaysia", "PH": "Philippines",
    "TR": "Turkey", "SA": "Saudi Arabia", "AE": "United Arab Emirates",
    "CL": "Chile", "CO": "Colombia", "PE": "Peru",
    "DE": "Germany", "FR": "France", "NL": "Netherlands", "IT": "Italy",
    "ES": "Spain", "IE": "Ireland", "BE": "Belgium", "AT": "Austria",
    "FI": "Finland", "PT": "Portugal", "GR": "Greece", "LU": "Luxembourg",
}


def country_from_iso2(code: str | None) -> str | None:
    """'US' -> 'United States'. An unknown code is kept as-is rather than
    collapsed into Other, so a rare market stays visible and traceable."""
    if not code:
        return None
    key = code.strip().upper()
    return _ISO2.get(key, key)


def currency_of(country: str) -> str:
    """The currency a company from this country is normally priced in.
    Unknown countries return 'Other' — never a guess."""
    name = (country or "").strip()
    if name in _EUROZONE:
        return "EUR"
    return _CURRENCY_BY_COUNTRY.get(name, UNKNOWN)


def region_of(country: str) -> str:
    """A coarse region, chosen so a matrix stays readable (5 buckets at most)."""
    name = (country or "").strip()
    if name in _EUROZONE:
        return "Europe"
    return _REGION_BY_COUNTRY.get(name, UNKNOWN)
