---
title: "Self-hosted personal finance app: run Aurelio on your own computer"
description: "Aurelio is a self-hosted personal finance app for Windows, macOS and Linux. It needs Git, Node.js 22 or later and uv; one command builds it, starts it on localhost:8000 and opens the browser, on an invented household or on your own records."
parent: "Guides"
nav_order: 1
---

# Self-hosted personal finance app: run Aurelio on your own computer

**Aurelio is an open-source, self-hosted personal finance app: it runs on your own computer,
on Windows, macOS or Linux, from one command, and keeps your records in a single file on your
machine.** It needs three tools: Git, Node.js 22 or later and uv. The start script builds the web
interface, starts the server on `http://localhost:8000` and opens your browser. Start it with
the demo flag the first time and you get an invented household to click through before you
type in a single figure of your own.

## What do you need to run it?

| Tool | What Aurelio uses it for | Where to get it |
|---|---|---|
| Git | downloading the code, and updating it later | [git-scm.com](https://git-scm.com) |
| Node.js 22 or later | building the web interface (npm comes with it) | [nodejs.org](https://nodejs.org) |
| uv | installing and running the Python side; it fetches Python 3.12 by itself if your computer does not have it | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |

Nothing else: no database server, no Docker, no account with Aurelio. Your records go in a
single file that the first start creates.

## Try it on the demo first

On macOS and Linux:

```bash
git clone https://github.com/LosaLosSantos/aurelio-finance.git
cd aurelio-finance
./start.sh --demo
```

On Windows, in PowerShell:

```powershell
git clone https://github.com/LosaLosSantos/aurelio-finance.git
cd aurelio-finance
./start.ps1 -Demo
```

The first start installs the interface's packages into `frontend/node_modules` and the
Python ones into `backend/.venv`, so it takes longer than the starts after it.

The demo is a new file, `backend/demo.db`, built on first use. It holds an invented household
in Hamburg: a salary of €3,400 a month into a "Demo Bank"; six expenses, from a €1,050
mortgage payment to a €540 yearly home insurance; a "Demo Broker" with an MSCI World ETF, an
emerging markets ETF, a euro government bond ETF and a few SAP shares; a flat worth €305,000
with a €199,500 mortgage; a €300 monthly plan into the world fund; and three goals, one of
them a car. Every date is counted back from the day the file is built, so its history ends on
that day.

The positions are real listings, so prices, dividends and the
[look-through](etf-overlap-and-portfolio-x-ray.md) have something to find once the app is
running. Fetching them needs an internet connection; building the demo does not.

Your own records are never touched by the demo: it refuses to be built into `data.db`, and
started without the flag, the app is back on your own file. To build the demo again from
scratch, delete `backend/demo.db` and start with the flag.

## Start it on your own records

```bash
./start.sh                 # macOS and Linux
```

```powershell
./start.ps1                # Windows
```

Your records live in `backend/data.db`. If your money is not mostly in euros, set the base
currency first, in Profile: it is the currency every total is shown in and the one each new
record proposes. See [One currency](how-to-calculate-net-worth.md#one-currency) for how amounts
in other currencies enter totals and how unavailable conversion rates are reported.

Then, under Records:

1. **Wealth**: add each bank or broker, its cash ("Actual cash" on a date), and a situation,
   which is a dated list of what that account holds.
2. **Cash flow**: your income and expenses, each with the day it starts and the account it
   is paid into or out of.
3. **Real assets** and **Debts**: a home, a car, the loan that finances it.

[How to calculate net worth](how-to-calculate-net-worth.md) explains what each of these does
to the totals.

## Options

| macOS and Linux | Windows | What it does |
|---|---|---|
| `--demo` | `-Demo` | starts on the demo household |
| `--no-browser` | `-NoBrowser` | starts without opening a browser |

## When PowerShell refuses to run the script

If PowerShell says that running scripts is disabled on this system, start it this way:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Demo
```

The bypass applies to that one command and changes no setting on your computer. Leave out
`-Demo` to start on your own records.

## How do you update it?

```bash
git pull
./start.sh                 # or ./start.ps1 on Windows
```

`uv run` brings the Python side in line with the new version by itself. The interface's
packages are installed only when `frontend/node_modules` is missing, so if an update adds one
and the build stops on a missing package, run `npm install` in `frontend/` once.

When an update changes the database's format, Aurelio copies the file first, next to it, as
`data.db.bak-<date>-<time>-before-migration-<from>-to-<to>`. It refuses to start if it cannot
make the copy, and if the change fails it puts the copy back.

## Where are your records kept?

All of them are in one SQLite file, `backend/data.db`. To back it up, copy the file while
Aurelio is stopped. To move to another computer, install Aurelio there and copy the file into
`backend/`. Git ignores `*.db` files and `backend/.env` (local settings), so `git pull`
never touches your records or those settings.

The server listens on your own computer only (`localhost`), and it has no login. It is meant
to be opened in the browser of the machine it runs on, not exposed to a network.

## For developers

Run `uv run pytest` in `backend/` and `npm test` in `frontend/`. For hot reload, run
`uv run uvicorn app.main:app --port 8000` in `backend/` and `npm run dev` in `frontend/`.

## Questions

**Is Aurelio free?** Yes: it is open source under the MIT license. The optional AI uses the
GitHub Copilot subscription authenticated on the machine; see
[GitHub Copilot usage in Aurelio](github-copilot-usage.md).

**Does it need an internet connection?** Your records and the totals built from them do not.
Market prices, fund compositions, exchange rates and the AI do.

**Is there a mobile app or a Docker image?** No. Aurelio is a web app served by your own
computer, opened in that computer's browser; the start script runs it directly.

**Does it connect to my bank?** No. You record balances and positions yourself; see
[Personal finance without bank sync](personal-finance-without-bank-sync.md).

## Next

- [Use Aurelio with GitHub Copilot](github-copilot-models.md), if you want the chat and the
  analysis.
- [How to calculate net worth](how-to-calculate-net-worth.md), to read the Dashboard.
