# Wrapify

**Spotify listening analytics platform with ETL pipeline, analytics API, and interactive dashboard**

Wrapify is a unified monorepo that extracts your Spotify listening history, analyzes it, and presents beautiful visualizations through an interactive dashboard. It consists of three main services:

- **ETL Pipeline**: Automated data extraction from Spotify API with Prefect orchestration
- **Analytics API**: FastAPI service for querying listening statistics
- **Web Dashboard**: Interactive Streamlit dashboard with visualizations

## Features

- 🎵 **Automated ETL**: Incremental data extraction from Spotify's Recently Played API
- 📊 **Rich Analytics**: Monthly listening statistics, top artists, tracks, and genres
- 🎨 **Interactive Dashboard**: Beautiful visualizations with Streamlit and Altair
- 🔄 **Workflow Orchestration**: Prefect-powered ETL with monitoring and scheduling
- 🐳 **Docker Ready**: Multi-service Docker Compose setup for easy deployment
- 🧪 **Well Tested**: Comprehensive test suite with pytest

## Quick Start

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) for dependency management
- PostgreSQL database
- Spotify Developer Account ([register here](https://developer.spotify.com/dashboard))

### Installation

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd wrapify
   ```

2. **Install dependencies:**
   ```bash
   uv sync
   ```

3. **Set up Spotify API:**
   - Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
   - Create an app to get your Client ID and Client Secret
   - Set a Redirect URI (e.g., `http://localhost:8888/callback`)

4. **Configure environment variables:**

   Environment variables are managed through Docker Compose. You can either:
   - Set them in your shell environment before running `docker compose`
   - Create a `.env` file in the project root (Docker Compose will automatically load it)

   Required variables:
   ```bash
   # Spotify API credentials
   SPOTIPY_CLIENT_ID=your_client_id_here
   SPOTIPY_CLIENT_SECRET=your_client_secret_here
   SPOTIPY_REDIRECT_URI=http://localhost:8888/callback

   # PostgreSQL configuration (use defaults for docker compose)
   POSTGRES_USER=db_user
   POSTGRES_SECRET=db_password
   DB_HOST=postgres  # or localhost for local development
   DB_PORT=5432
   DB_NAME=spotify
   ```

5. **Set up Prefect blocks** (required for ETL):
   ```bash
   prefect server start  # In a separate terminal
   uv run python -m etl.prefect_blocks.create_blocks
   ```
   This will interactively create the required Prefect blocks for Spotify API and PostgreSQL.

### Usage

#### Run ETL Pipeline

Extract and process your Spotify listening history:

```bash
uv run python -m etl.flow
```

Calculate analytics statistics:

```bash
uv run python -m etl.analytics.flow
```

#### Start Analytics API

```bash
uv run uvicorn api.main:app --reload
```

Access API documentation at: http://localhost:8000/docs

#### Launch Dashboard

```bash
uv run streamlit run src/web/app.py
```

Access dashboard at: http://localhost:8501

### Docker Deployment

Run all services with Docker Compose:

```bash
# Start API and Dashboard
docker compose up

# Include ETL service (uses profile)
docker compose --profile etl up etl

# Include local PostgreSQL database
docker compose up postgres api web
```

## Project Structure

```
wrapify/
├── src/
│   ├── etl/          # ETL pipeline and analytics flows
│   ├── api/          # FastAPI analytics service
│   └── web/          # Streamlit dashboard
├── tests/            # Test suite
├── docker/           # Dockerfiles for each service
├── pyproject.toml    # Unified dependencies
└── docker-compose.yaml
```

## Architecture

### ETL Pipeline

1. **Extract**: Fetches recently played tracks from Spotify API (incremental)
2. **Transform**: Cleans data, extracts track/artist metadata
3. **Load**: Loads data into PostgreSQL via staging tables
4. **Analytics**: Calculates aggregated statistics

The pipeline uses Prefect for orchestration and can be scheduled to run automatically.

### Database Schema

- **prod.played**: Listening history with timestamps
- **prod.track**: Track metadata (title, duration, popularity)
- **prod.artist**: Artist metadata (name, genres, followers, images)
- **prod.track_artist**: Track-artist relationships
- **stats.artists_listened_monthly**: Monthly artist statistics

### API Endpoints

- `GET /top-artist?year=YYYY&month=MM`: Returns most listened artist for a given month

### Dashboard Features

- **Favorites Tab**: Top artists, tracks, and genres
- **Metrics Tab**: Distribution analysis with interactive histograms
- **Recently Played Tab**: Chronological listening history

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src

# Run specific test file
uv run pytest tests/test_extract_recently_played.py -v
```

### Code Quality

```bash
# Format code
uv run ruff format .

# Lint code
uv run ruff check .

# Fix linting issues
uv run ruff check --fix .
```

### Prefect Deployment

For production deployments with scheduling:

```bash
# Deploy flows to Prefect server/cloud
prefect deploy

# Set up automation to trigger analytics after ETL completes
# (Configure in Prefect UI using the 'new-data' event)
```

## Configuration

All configuration is managed through environment variables defined in `docker-compose.yaml`:

- **Spotify API**: `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI`
- **PostgreSQL**: `POSTGRES_USER`, `POSTGRES_SECRET`, `DB_HOST`, `DB_PORT`, `DB_NAME`
- **API**: `PORT` (optional, defaults to 8000)

For local development without Docker, export these variables in your shell or create a `.env` file.

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes and add tests
4. Run tests and linting: `uv run pytest && uv run ruff check .`
5. Commit your changes: `git commit -am 'Add feature'`
6. Push to the branch: `git push origin feature-name`
7. Submit a pull request

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Built with [Prefect](https://www.prefect.io/) for workflow orchestration
- [Spotipy](https://spotipy.readthedocs.io/) for Spotify API integration
- [Streamlit](https://streamlit.io/) for the dashboard
- [FastAPI](https://fastapi.tiangolo.com/) for the analytics API
