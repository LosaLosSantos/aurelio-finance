# Aurelio

[![CI](https://github.com/LosaLosSantos/aurelio-finance/actions/workflows/ci.yml/badge.svg)](https://github.com/LosaLosSantos/aurelio-finance/actions/workflows/ci.yml)

**Aurelio** is a wealth-management and financial-planning app that runs on your
own computer, with an AI advisor you can talk to. Your records are kept on your
machine. The AI part is optional: it goes through
[OpenRouter](https://openrouter.ai) with your own key.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/LosaLosSantos/aurelio-finance/main/docs/banner-dark.gif">
  <img alt="Aurelio: everything you own in one place. An animation: the net worth and what makes it up, the countries inside the funds, a question about 1,235 euros left each month answered with a split, and a proposal you confirm or reject." src="https://raw.githubusercontent.com/LosaLosSantos/aurelio-finance/main/docs/banner-light.gif" width="100%">
</picture>

## Try it on invented data

You need [Git](https://git-scm.com), [Node.js](https://nodejs.org) 22 or later
and [uv](https://docs.astral.sh/uv/getting-started/installation/). Then:

```bash
git clone https://github.com/LosaLosSantos/aurelio-finance.git
cd aurelio-finance
./start.sh --demo          # macOS and Linux
```

```powershell
git clone https://github.com/LosaLosSantos/aurelio-finance.git
cd aurelio-finance
./start.ps1 -Demo          # Windows, in PowerShell
```

If PowerShell says that running scripts is disabled, use
`powershell -ExecutionPolicy Bypass -File .\start.ps1 -Demo`.

The first start installs what it needs inside the folder and opens
<http://localhost:8000> on an invented household, kept in a file of its own.
Start without the flag to use your own data.

## Run it on your own data

```bash
./start.sh                 # macOS and Linux
```

```powershell
./start.ps1                # Windows
```

Your records live in `backend/data.db`. Before an update changes its format,
the app saves a copy next to it.

## What it does

- **Wealth**: your banks and brokers, their cash, and dated situations of what
  you hold.
- **Portfolio**: every position priced from the market, with its cost, gain and
  dividends.
- **Look-through**: what your funds really hold, by country, sector, company
  and currency.
- **Plans, homes and debts**: recurring investments, real assets and the loans
  that finance them.
- **Cash flow and goals**: income, expenses, savings rate, and the return each
  goal needs.
- **Ask Aurelio**: a chat that answers from your own records, can search the
  web, and proposes every change as a card you confirm.
- **The analysis**: an analyst and a confidant who knows you argue over your
  portfolio, and a synthesis says what to look at first.

[How Aurelio reasons](docs/how-aurelio-reasons.md) explains the ideas
underneath.

## The AI part

1. Create an account at <https://openrouter.ai>, add credit, and create a key at
   <https://openrouter.ai/keys>.
2. Copy `backend/.env.example` to `backend/.env` and set `OPENROUTER_API_KEY`.

The default model is Claude Opus 5.5 ($4 per million input tokens, $20 per
million output tokens); you can pick another in the chat. What it cost,
measured in October 2026 (the chat's rows on 9 October, on a test database):

| | cost |
|---|---|
| A first question, answered in one round | $0.10 |
| A follow-up, answered in one round | $0.013 to $0.034 |
| A first question that searched the web twice, answered in two rounds | $0.12 |
| Each web search, included in the row above | $0.0073 to $0.0075 |
| An analysis | $0.33 to $0.51 |

## Development

`uv run pytest` in `backend/` and `npm test` in `frontend/`. For hot reload,
run `uv run uvicorn app.main:app --port 8000` in `backend/` and `npm run dev` in
`frontend/`.

## License

MIT, see [LICENSE](LICENSE).
