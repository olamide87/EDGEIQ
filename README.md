# EDGE IQ v0.6A

EDGE IQ is a typed, local-first research application for NFL player-prop line
shopping, scheduled authorized-odds ingestion, projection review, and paper-trading
analytics. v0.6A adds the first deterministic learned WR-receptions research
candidate on top of the reproducible data, point-in-time feature, baseline, and
governed evaluation layers.

EDGE IQ does not scrape sportsbook sites, automate logins, place wagers, or claim
that any model or recommendation will be profitable. The Odds API remains the only
real-feed adapter included by the project.

Project direction and system design are documented in [ROADMAP.md](ROADMAP.md) and
[ARCHITECTURE.md](ARCHITECTURE.md). Contributions should follow
[CONTRIBUTING.md](CONTRIBUTING.md).

## Setup

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Windows: Copy-Item .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

For a database already managed by Alembic, run `alembic upgrade head` before starting.
The legacy local `data/edgeiq.db` may contain application-created tables without a
revision stamp. Do not stamp, delete, or upgrade that file casually; back up and
handle it through a separate migration decision. v0.5A schema validation uses a
fresh ignored SQLite database. See [database migration notes](docs/database-migrations.md).
Swagger is available at `http://127.0.0.1:8000/docs`.

## Historical NFL data pipeline

Downloaded data and processed datasets are ignored by Git. The commands below use
`nflreadpy`; they require internet access and must be run only for datasets whose
license and intended use have been reviewed.

```text
python -m app.cli data-download --seasons 2021 2022 2023 2024 2025 --datasets player_stats schedules rosters weekly_rosters snap_counts participation injuries depth_charts
python -m app.cli data-manifest
python -m app.cli build-wr-dataset --seasons 2021 2022 2023 2024 2025
```

Play-by-play is supported but omitted from the default cache because it is much
larger and is not needed to produce the v0.5A table. Tests inject tiny synthetic CSV
fixtures and make no network calls. See [research/README.md](research/README.md) and
[data-source attribution](docs/data-sources.md).

The first learned model is a research-only Poisson regression trained and evaluated
chronologically against the governed v0.5C baselines. See the
[WR Poisson model note](docs/wr-poisson-model.md). nflverse does not provide
historical player-prop odds, and projection accuracy does not establish betting
profitability.

## WR feature engineering

```text
python -m app.cli build-wr-features --seasons 2021 2022 2023 2024 2025
python -m app.cli feature-registry
python -m app.cli validate-wr-features --path data/processed/wr_receptions_features.parquet
python research/experiments/run_v05b_feature_audit.py
```

Player rolling features are shifted by one completed game and carry across seasons;
season-to-date, team, and opponent histories reset each season. The builder updates
history only after every row in a game is materialized. Missing data remains visible,
with explicit indicators for unavailable snap and route-participation history.

The registry contains candidate features only. No feature is promoted merely because
it sounds predictive; usefulness is evaluated in v0.5C and v0.5D. See
[the feature registry](feature_store/README.md) and
[ADR 0006](docs/decisions/0006-point-in-time-feature-semantics.md).

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service and version status |
| `GET` | `/props` | Props with raw and, when supported, fair probability |
| `GET` | `/props/best` | Best line first, then best price, with selection reason |
| `POST` | `/projections` | Projection, confidence, freshness, EV, and recommendation |
| `POST` | `/projections/wr-receptions` | Baseline Poisson WR-receptions projection |
| `GET` | `/recommendations` | Recommendation history and rejection reasons |
| `POST` | `/paper-bets` | Record a paper bet from a recommendation |
| `GET` | `/paper-bets` | List paper bets and their close/settlement state |
| `POST` | `/paper-bets/{id}/close` | Record the closing market and CLV |
| `POST` | `/paper-bets/{id}/settle` | Grade a paper bet as win, loss, or push |
| `GET` | `/performance` | Aggregate and segmented paper performance |
| `POST` | `/ingestion/run` | Run one authorized provider or all enabled providers once |
| `GET` | `/ingestion/jobs` | Ingestion audit history and categorized failures |
| `GET` | `/providers/health` | Provider latency, records, failures, and health state |
| `GET` | `/odds/history` | Filterable persisted snapshot history |
| `GET` | `/odds/movements` | Contract movement and multi-book consensus |

## Automated ingestion

Provider adapters remain behind the original `OddsProvider` interface and are
registered by key. The built-in registry contains `mock` and `theoddsapi`; future
adapters must use licensed or authorized sources. No sportsbook, PrizePicks, Sleeper,
or Underdog scraping is included.

Run one ingestion locally:

```bash
python -m app.cli ingest-once --provider mock
python -m app.cli provider-health
```

Or call the API:

```bash
curl -X POST http://127.0.0.1:8000/ingestion/run \
  -H "Content-Type: application/json" \
  -d '{"provider":"mock"}'
```

Each execution records a correlation ID, start/end time, attempts, provider, status,
row count, categorized error, health metrics, payload hash, and quality flags.
Payload hashes exclude capture time and suppress a consecutive unchanged response
without deleting its audit batch.

Set `INGESTION_ENABLED=true` to start the in-process APScheduler loop with FastAPI.
It is disabled by default, and tests explicitly prevent background startup. The
in-process scheduler is suitable for one local API instance. A multi-instance or
production deployment should move the same `IngestionService` jobs to Celery, RQ,
a managed cloud scheduler, or another distributed executor with a shared lock.

Quality checks flag malformed payloads, missing names, unsupported markets, invalid
odds, stale events, duplicate contracts, alias variations, and impossible lines.
Raw provider player names are retained while canonical players are resolved through
provider-specific alias records.

Market consensus uses the latest observation from each independent sportsbook and
returns median line and median implied probability only when at least two books
contribute.

Legacy v0.2 projection payloads remain valid. A richer request can include input
freshness and confidence components:

```json
{
  "prop_line_id": 1,
  "model_probability": 0.6,
  "projected_value": 7.2,
  "model_name": "receptions-v2",
  "captured_at": "2026-07-15T22:00:00Z",
  "confidence": {
    "data_quality": 0.9,
    "sample_size": 0.8,
    "role_stability": 0.85,
    "injury_certainty": 1.0,
    "matchup_certainty": 0.7,
    "market_stability": 0.8
  }
}
```

Paper lifecycle examples:

```bash
curl -X POST http://127.0.0.1:8000/paper-bets \
  -H "Content-Type: application/json" \
  -d '{"recommendation_id":1,"stake":"5.00"}'

curl -X POST http://127.0.0.1:8000/paper-bets/1/close \
  -H "Content-Type: application/json" \
  -d '{"closing_line":6.5,"closing_odds":-110}'

curl -X POST http://127.0.0.1:8000/paper-bets/1/settle \
  -H "Content-Type: application/json" \
  -d '{"outcome":"WIN","result_value":8}'
```

## Formulas and decisions

American odds are converted to decimal odds, then:

```text
raw implied probability = 1 / decimal odds
fair probability_i = raw probability_i / sum(raw probabilities for the opposing pair)
expected return per $1 = model probability * decimal odds - 1
overall confidence = sum(component_i * weight_i) / sum(weights)
```

Fair probability is only populated when the same sportsbook, event, player, market,
and line has a complete OVER/UNDER or YES/NO pair. A one-sided offer reports raw
implied probability and `fair_market_probability: null`; it is never called vig-free.

Best-line ordering is threshold-first: lowest line for OVER, highest line for UNDER,
then best decimal price. Binary markets compare price only. Projection EV is computed
against the selected best offer, not blindly against the requested offer.

Default policy:

- `PASS`: negative EV, confidence below 50%, or data older than 60 minutes.
- `WATCH`: positive edge that misses the 5% BET EV threshold, 70% BET confidence,
  or 15-minute freshness threshold.
- `BET`: all BET thresholds pass. This is still a paper-only label.

CLV records line movement as `closing line - bet line`, price movement as
`bet decimal odds - closing decimal odds`, and whether the entry beat the close.
Percentage CLV is `bet decimal odds / closing decimal odds - 1`, but only when the
bet and close have the same line (or both are line-less binary contracts). Different
lines are not treated as mathematically identical contracts.

## Baseline WR-receptions model

The model uses a Poisson count distribution and is deliberately labeled **baseline,
not production-grade**:

```text
projected targets = team pass attempts * route participation * targets per route
                    * product(contextual multipliers)
Poisson rate = projected targets * catch probability
```

The 10th, 50th, and 90th Poisson percentiles are returned as floor, median, and
ceiling. Integer lines include an explicit push probability. The model does not yet
learn from historical play-by-play data, model overdispersion, or account for
dependencies between team and player outcomes.

## Paper bankroll and analytics

Defaults are a $1,000 paper bankroll, $5 unit, $10 single stake, $50 weekly exposure,
$15 active player exposure, and $20 active event exposure. Duplicate unsettled bets
on the same player/event/market/side are rejected. Other same-player and same-event
bets are flagged as correlated; correlation flags are warnings, not covariance models.

`GET /performance` reports record, amount risked, net profit, ROI, average entry EV,
average valid percentage CLV, CLV hit rate, market/book/rating splits, and maximum
drawdown from chronologically settled results. Financial values are stored with
`Decimal`-backed SQL numeric columns.

## CLI and provider

The v0.1/v0.2 CLI remains unchanged:

```bash
python -m app.cli --demo
python -m app.cli --provider theoddsapi  # requires ODDS_API_KEY
```

Normalized provider offers can be stored with `app.persistence.persist_offers`.
Every odds row and model request carries `captured_at` data.

## Configuration

`.env.example` documents all settings. Important defaults include:

| Setting | Default |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./data/edgeiq.db` |
| `BET_EV_THRESHOLD` | `0.05` |
| `MIN_WATCH_CONFIDENCE` / `MIN_BET_CONFIDENCE` | `0.50` / `0.70` |
| `FRESH_DATA_SECONDS` / `STALE_DATA_SECONDS` | `900` / `3600` |
| `MAX_WEEKLY_EXPOSURE` | `50` |
| `MAX_PLAYER_EXPOSURE` / `MAX_EVENT_EXPOSURE` | `15` / `20` |
| `INGESTION_ENABLED` | `false` |
| `INGESTION_POLL_INTERVAL_MINUTES` | `15` |
| `PROVIDER_TIMEOUT_SECONDS` | `30` |
| `PROVIDER_RETRY_COUNT` | `2` |
| `INGESTION_STALE_EVENT_HOURS` | `6` |
| `ENABLED_PROVIDERS` | `mock` |

The six confidence weights are independently configurable and normalized by their
sum. For PostgreSQL, install a compatible driver and set a
`postgresql+psycopg://...` database URL; the domain models use portable SQLAlchemy
types.

## Validation

```bash
pytest -q
alembic upgrade head
alembic check
```
