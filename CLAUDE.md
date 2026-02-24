# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
export PYTHONPATH=$PYTHONPATH:.
python -m pytest tests/ -v

# Run a single test file
python -m pytest tests/test_risk_engine.py -v

# Run main audit
python sigma_guard.py

# Trade management CLI
python sg_console.py buy TICKER QTY PRICE --stop STOP_PRICE
python sg_console.py sell TICKER QTY PRICE
python sg_console.py list --type holdings
python sg_console.py report

# Build watchlist from public indices
python build_master_config.py
```

## External Dependencies (Required Directory Structure)

The project references a sibling `common/` directory that is **outside this repo**:

```
WORK/
├── common/
│   ├── config_manager.py   # SecretConfig class (Telegram tokens, API keys)
│   └── SG_config.yaml      # Watchlist definitions and system parameters
└── SG/                     # This project
```

`config/settings.py` resolves `parent.parent` from the project root to find `common/`. If `common/` is missing, the system degrades gracefully (no Telegram, empty watchlist).

## Architecture

**Sigma Guard** is a quantitative trading analytics system applying CPA audit principles. It analyzes a watchlist of stocks, produces risk scores, and sends reports via Telegram.

### Core Data Flow

```
sigma_guard.py (orchestrator)
    ↓ For each ticker in watchlist + DB holdings
    core/indicators.py       → Fetches 6y of daily data (yfinance), computes all indicators
    core/risk_engine.py      → Scores risk 0–100 across P1/P2/P4 components
    data/ledgers/            → Writes 53-column CSV audit record
    utils/visual_reporter.py → Prints console report with delta tracking
    utils/messenger.py       → Sends Telegram notification (smart HTML-safe splitting)
```

### Risk Scoring System (core/risk_engine.py)

- **P1 (Position, 30pts)**: Statistical position via multi-sigma (1y–5y windows)
- **P2 (Energy, 50pts)**: Momentum via MACD, Bollinger Band Width, MFI, RSI
- **P4 (Trap, 20pts)**: False breakout detection via ADX + R²
- **Livermore Discount**: −10% to −50% EMA-smoothed confirmation gate (requires ADX ≥ 25, R² ≥ 0.5, MFI ≥ 40)
- **Output**: Risk Level 1–9, SOP action label, position sizing recommendation

### Key Indicators (core/indicators.py)

Multi-sigma (1y/2y/3y/4y/5y), RSI-14, MFI-14, ADX-14, Bollinger Bands (20), Disparity-120, MACD, R-Squared. Returns a synchronized `(target_df, bench_df)` pair after fetching and aligning benchmark data.

### Database (core/db_handler.py)

SQLite at `data/db/`. Two tables:
- `holdings`: ticker, qty, avg_price, entry_stop, last_updated
- `trades`: ticker, type (BUY/SELL), qty, price, fee, total_amount, profit, trade_date

`record_buy()` updates average cost basis; `record_sell()` calculates realized P&L.

### Ledger Format (data/ledgers/)

53-column CSV per David's master spec. Includes ticker metadata, multi-sigma values, technical indicators, macro snapshot (VIX/US10Y/DXY), P1/P2/P4 raw + EMA scores, and post-audit T+20 return tracking.

### Telegram Messenger (utils/messenger.py)

Splits messages at paragraph boundaries to stay under Telegram's 4096-char limit. Force-splits paragraphs > 3000 chars while preserving HTML tags (`<b>`, `<br>`, etc.). Rate-limited at 0.5s between parts.

### Currency Formatting

KRW (integers, no decimals), USD (3 decimals), JPY/CNY/HKD handled via global formatting in `utils/visual_reporter.py`. Regional mapping (benchmark → region) lives in `utils/market_utils.py`.

## Important Conventions

- **Type integrity**: Distinguish `None` (missing data) from `0.0` (valid zero). The codebase is strict about this.
- **Delta tracking**: Previous risk scores are stored and compared; `▲`/`▼` symbols indicate changes in `visual_reporter.py`.
- **EMA smoothing**: Alpha = 0.5 applied to risk components to prevent single-day whipsaws.
- **OCI constraints**: ~1GB RAM limit — prefer generators and batch processing over loading full datasets.
- **No linter configured**: Code style follows existing patterns in the repo.
