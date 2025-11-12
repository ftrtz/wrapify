# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Wrapify is a Spotify listening analytics platform built as a monorepo with three main services:
- **ETL Pipeline**: Prefect-orchestrated data extraction from Spotify API
- **Analytics API**: FastAPI service for querying statistics
- **Web Dashboard**: Streamlit-based interactive visualizations

## Common Commands

### Development Setup
```bash
# Install dependencies
uv sync

# Set up environment variables
# Either export them in your shell or create a .env file that docker-compose will load
# Required: SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
# And PostgreSQL config: POSTGRES_USER, POSTGRES_SECRET, DB_HOST, DB_PORT, DB_NAME

# Start Prefect server (required for ETL)
prefect server start

# Create Prefect blocks (first-time setup)
uv run python -m etl.prefect_blocks.create_blocks
```

### Running Services
```bash
# ETL pipeline (extract Spotify data)
uv run python -m etl.flow

# Analytics calculation (after ETL completes)
uv run python -m etl.analytics.flow

# API server
uv run uvicorn api.main:app --reload

# Dashboard
uv run streamlit run src/web/app.py
```

### Testing and Code Quality
```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src

# Run specific test file
uv run pytest tests/test_extract_recently_played.py -v

# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .
```

### Docker
```bash
# Start API and dashboard (uses external DB)
docker compose up

# Include PostgreSQL database
docker compose up postgres api web

# Run ETL (uses profile)
docker compose --profile etl up etl
```

### Prefect Deployment
```bash
# Deploy flows to Prefect server/cloud
prefect deploy
```

## Architecture

### ETL Pipeline Flow (`src/etl/flow.py`)

The `spotify_etl` flow follows these steps:

1. **create_db_tables**: Creates staging and production schemas/tables
2. **extract_played**: Fetches recently played tracks from Spotify API (incremental, using last timestamp from DB)
3. If new data exists:
   - **extract_track**: Extracts unique track metadata from played records
   - **transform_track**: Cleans data, creates track-artist relationships, finalizes schemas
   - **extract_artist**: Fetches full artist metadata from Spotify (genres, followers, images)
   - **load_tables**: Loads CSVs into staging schema
   - **insert_prod**: Upserts from staging into production schema
   - **cleanup**: Removes temporary CSV files
   - **emit_event**: Emits "new-data" event to trigger analytics flow

All data flows through CSV intermediates in `src/etl/data/` before loading to database.

### Analytics Flow (`src/etl/analytics/flow.py`)

The `analytics_flow` recalculates statistics (currently full recalculation, not incremental):
- **reset_stats_tables**: Drops and recreates stats schema tables
- **calc_artist_monthly**: Aggregates monthly listening statistics per artist

Can be automated to run after ETL via Prefect automation triggered by "new-data" event.

### Database Schemas

The application uses three PostgreSQL schemas:

- **staging**: Temporary tables for ETL loading (e.g., `staging.played`, `staging.track`)
- **prod**: Production tables with full data:
  - `prod.played`: Listening history (track_id, played_at, unix_timestamp)
  - `prod.track`: Track metadata (track_id, title, duration_ms, popularity)
  - `prod.artist`: Artist metadata (artist_id, name, genres, followers, images)
  - `prod.track_artist`: Many-to-many relationship between tracks and artists
  - `prod.audio_features`: Track audio features (not yet fully implemented)
- **stats**: Aggregated analytics tables:
  - `stats.artists_listened_monthly`: Monthly artist listening statistics

Schema names are defined as constants in the ETL flow files. SQL templates use Jinja2 to inject schema names dynamically.

### Prefect Blocks

The ETL requires three Prefect Secret blocks (created via `etl.prefect_blocks.create_blocks`):

1. **spotipy**: JSON with `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`
2. **spotify-access-token**: OAuth token cache (created during initial auth flow)
3. **spotify-postgresql**: SQLAlchemy connector for database access

Blocks must be created before running ETL flows.

### Configuration

Configuration relies entirely on environment variables defined in `docker-compose.yaml`:
- For Docker: Variables are injected via docker-compose.yaml with sensible defaults
- For local development: Export variables in your shell or create a `.env` file (docker-compose will load it)

Schema constants (`PROD_SCHEMA`, `STAGING_SCHEMA`, `ANALYTICS_SCHEMA`) are defined directly in the ETL flow files that use them:
- `src/etl/flow.py`: Defines PROD_SCHEMA and STAGING_SCHEMA
- `src/etl/analytics/flow.py`: Defines PROD_SCHEMA and ANALYTICS_SCHEMA

The API (`src/api/main.py`) constructs the DATABASE_URL from individual environment variables using `os.getenv()`.

### Module Imports

Use module-style imports when running with `uv run`:
- ETL: `python -m etl.flow`
- Analytics: `python -m etl.analytics.flow`
- API: `uvicorn api.main:app`
- Dashboard: `streamlit run src/web/app.py`

### Web Dashboard (`src/web/`)

- `load_tables.py`: Loads data from PostgreSQL using polars + connectorx (fast!)
- `transform_tables.py`: Aggregation functions for dashboard (top artists/tracks)
- `app.py`: Streamlit multi-page app with tabs for Favorites, Metrics, Recently Played

Dashboard uses polars DataFrames (not pandas) for better performance with large datasets.

## Key Technical Details

- **Python Version**: 3.13+ (specified in pyproject.toml)
- **Package Manager**: uv (not pip/poetry)
- **Prefect API URL**: Configured in `pyproject.toml` under `[tool.prefect]` (defaults to localhost:4200)
- **Incremental Loading**: ETL tracks last played timestamp to only fetch new data
- **OAuth Caching**: Spotify tokens cached in `src/etl/.cache` file
- **SQL Templating**: All SQL files use Jinja2 for schema name injection

## Development Workflow

When modifying the ETL pipeline:
1. Update task functions in `src/etl/flow.py`
2. Modify SQL templates in `src/etl/sql/` if schema changes needed
3. Update utility functions in `src/etl/utils.py` for data transformations
4. Add tests in `tests/` (use pytest fixtures for sample data)
5. Run tests before committing: `uv run pytest`

When modifying the API:
1. Update endpoints in `src/api/main.py`
2. Use SQLAlchemy for database queries
3. Test with FastAPI's interactive docs at `/docs`

When modifying the dashboard:
1. Update data loading in `src/web/load_tables.py` (uses polars)
2. Add transformations in `src/web/transform_tables.py`
3. Modify UI in `src/web/app.py` (Streamlit + Altair charts)

## Important Notes

- The ETL pipeline emits a "new-data" event after successful runs to trigger analytics flow via Prefect automation
- The `prefect.yaml` file defines two deployments: `spotify-etl` (hourly cron) and `analytics-flow` (event-triggered)
- Work pool name in `prefect.yaml` is currently set to "dongbin-work-pool" - update for your environment
- Tests use pytest without fixtures currently - sample data is constructed inline
- All services require PostgreSQL connection - use Docker Compose postgres service or external DB
