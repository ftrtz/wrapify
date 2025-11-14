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

#### Local Development (Direct Execution)
```bash
# Run ETL flow once (for testing)
uv run python -m etl.flow

# Run analytics flow once (for testing)
uv run python -m etl.analytics.flow

# Serve both flows (long-running process that listens for scheduled/triggered runs)
uv run python -m etl.serve

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
# Start all services (API, dashboard, ETL, and PostgreSQL)
docker compose up

# Start specific services
docker compose up postgres api web etl

# Start just the ETL container (serves flows in long-running mode)
docker compose up etl

# View logs
docker compose logs -f etl

# Check ETL container health
curl http://localhost:8080/health
```

### Prefect Deployment

The project uses **container-based serve deployments** instead of work pools:

```bash
# Local: Serve flows in a long-running process (for development/testing)
uv run python -m etl.serve

# Production: Run the ETL container which serves flows automatically
docker compose up etl

# The container registers deployments with Prefect and listens for:
# - Scheduled runs (ETL runs hourly via cron)
# - Manual triggers from Prefect UI
# - Automated analytics triggering (via task completion events)
```

**Key differences from work pool deployments:**
- No `prefect deploy` command needed
- No work pool or worker required
- Flows served directly from container using `.serve()` method
- Container runs continuously, polling Prefect API for scheduled/triggered runs
- Automation setup is integrated and automatic
- Simpler deployment model with fewer moving parts

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
   - **insert_prod**: Upserts from staging into production schema (triggers analytics via automation)
   - **cleanup**: Removes temporary CSV files

All data flows through CSV intermediates in `src/etl/data/` before loading to database.

The analytics flow is automatically triggered when the `insert_prod` task completes successfully via a Prefect automation.

### Analytics Flow (`src/etl/analytics/flow.py`)

The `analytics_flow` recalculates statistics (currently full recalculation, not incremental):
- **reset_stats_tables**: Drops and recreates stats schema tables
- **calc_artist_monthly**: Aggregates monthly listening statistics per artist

This flow is automatically triggered by a Prefect automation when the `insert_prod` task completes, ensuring analytics are calculated immediately after new data is loaded.

### Serve Deployment (`src/etl/serve.py`)

The serve script creates deployments, sets up automation, and serves both flows in a single long-running process:
- Uses Prefect's `.serve()` method to register deployments and listen for work
- **spotify-etl deployment**: Scheduled hourly (cron: `0 * * * *`)
- **analytics-flow deployment**: Triggered automatically via Prefect automation
- **Automation setup**: Automatically creates automation that triggers analytics when `insert_prod` task completes
  - Uses wildcard matching (`insert_prod*`) to match task names with random suffixes
  - Only triggers when new data is available (insert_prod only runs when there's new data)
- Runs in Docker container with health monitoring on port 8080
- Container automatically reconnects to Prefect server on restart
- No work pools or workers needed - flows execute directly in the container

The automation ensures analytics are calculated only when new data is loaded, avoiding unnecessary recalculations.

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
- ETL (single run): `python -m etl.flow`
- Analytics (single run): `python -m etl.analytics.flow`
- ETL + Analytics (serve mode): `python -m etl.serve`
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

- **Container-Based Deployments**: Flows are served from a long-lived Docker container using Prefect's `.serve()` method
- **No Work Pools Required**: The ETL container runs flows directly without needing work pools or workers
- **Deployment Configuration**: Both flows are configured in `src/etl/serve.py` with schedules and automation
- **ETL Schedule**: The `spotify_etl` flow runs hourly (cron: `0 * * * *`)
- **Automated Analytics**: The `analytics_flow` is automatically triggered when the `insert_prod` task completes
  - Automation is set up automatically by `serve.py` on startup
  - Uses task event matching with wildcards (`insert_prod*`) to handle Prefect's random task name suffixes
  - Only triggers when new data is available (conditional execution in ETL flow)
- **Manual Automation Setup**: If automation fails to create automatically, run `uv run python -m etl.setup_automation` manually
- **Health Monitoring**: ETL container exposes health endpoint at `http://localhost:8080/health`
- **Tests**: Use pytest without fixtures currently - sample data is constructed inline
- **Database**: All services require PostgreSQL connection - use Docker Compose postgres service or external DB
- **Legacy Files**: `prefect.yaml.backup-workpool-deployment` contains the old work pool deployment config (archived)
