# Aurelio

[![CI](https://github.com/LosaLosSantos/aurelio-finance/actions/workflows/ci.yml/badge.svg)](https://github.com/LosaLosSantos/aurelio-finance/actions/workflows/ci.yml)

**Aurelio** is a wealth-management and financial-planning app that runs on your
own computer, with an AI advisor you can talk to. Your records are kept on your
machine. The AI part is optional: model calls use the GitHub Copilot account
authenticated on this machine.

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
underneath. Guides, and how each number is worked out, are in the
[wiki](https://github.com/LosaLosSantos/aurelio-finance/wiki):
[how to calculate net worth](https://github.com/LosaLosSantos/aurelio-finance/wiki/how-to-calculate-net-worth),
[ETF overlap and portfolio X-ray](https://github.com/LosaLosSantos/aurelio-finance/wiki/etf-overlap-and-portfolio-x-ray),
[accumulating vs distributing ETFs](https://github.com/LosaLosSantos/aurelio-finance/wiki/accumulating-vs-distributing-etf),
[how many months of emergency fund](https://github.com/LosaLosSantos/aurelio-finance/wiki/how-many-months-of-emergency-fund-do-you-need)
and [how Aurelio uses GitHub Copilot](https://github.com/LosaLosSantos/aurelio-finance/wiki/github-copilot-usage).

## The AI part

1. Install GitHub Copilot CLI and sign in: `copilot login`.
2. Run `copilot --banner` once and accept GitHub's terms if prompted.
3. Copy `backend/.env.example` to `backend/.env` only if you want to override
   the default models.

The default is `claude-opus-5.5`. The chat model and the analysis roles can be
changed independently. Aurelio discovers the models available to the signed-in
Copilot account, so the chat menu reflects that account rather than a hard-coded
provider catalogue.

Model prompts include the financial records needed to answer the question.
Those prompts leave this machine and are processed by GitHub Copilot and its
model providers under the terms of the signed-in account. Copilot subscription
usage is not a dollar price, so Aurelio records token usage but leaves its
historical USD cost fields empty for Copilot-backed calls.
SDK transcripts and runtime logs use request-scoped temporary storage that is
removed when the request ends; the CLI's saved login and keychain remain available.

## Development

`uv run pytest` in `backend/` and `npm test` in `frontend/`. For hot reload,
run `uv run uvicorn app.main:app --port 8000` in `backend/` and `npm run dev` in
`frontend/`.

## License

MIT, see [LICENSE](LICENSE).
