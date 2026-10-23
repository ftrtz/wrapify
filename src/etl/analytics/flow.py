import os
from pathlib import Path
from prefect import flow, task
from prefect_sqlalchemy import SqlAlchemyConnector
from jinja2 import Template

# Database schemas
PROD_SCHEMA = "prod"
# Set ANALYTICS_SCHEMA=stats_dev locally to build stats without touching production's tables
ANALYTICS_SCHEMA = os.getenv("ANALYTICS_SCHEMA", "stats")

SQL_PATH = Path("src/etl/analytics/sql")

# Currently this flow recalculates all stats in each run (takes ~1 sec) - in the future we might want to do incremental updates


def get_db() -> SqlAlchemyConnector:
    """Connect via the DB_* env vars when set (local dev), else via the Prefect block.

    The block points at the docker-internal `wrapify-postgres` host, which is not
    reachable from a dev machine. The ETL container sets none of these vars.
    """
    if os.getenv("DB_HOST"):
        if ANALYTICS_SCHEMA == "stats":
            raise RuntimeError(
                "Refusing to rebuild the production 'stats' schema from a local run - "
                "set ANALYTICS_SCHEMA (e.g. stats_dev)"
            )
        db_url = f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_SECRET')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
        return SqlAlchemyConnector(connection_info=db_url)
    return SqlAlchemyConnector.load("spotify-postgresql")


@task
def reset_stats_tables():
    with get_db() as db:
        with open(SQL_PATH / "reset_stats_tables.sql", "r") as file:
            sql = Template(file.read()).render(
                prod_schema=PROD_SCHEMA, analytics_schema=ANALYTICS_SCHEMA
            )
            db.execute(sql)


@task
def calc_artist_monthly():
    with get_db() as db:
        with open(SQL_PATH / "calc_artist_monthly.sql", "r") as file:
            sql = Template(file.read()).render(
                prod_schema=PROD_SCHEMA, analytics_schema=ANALYTICS_SCHEMA
            )
            db.execute(sql)


@flow()
def analytics_flow():
    reset_stats_tables()
    calc_artist_monthly()


if __name__ == "__main__":
    analytics_flow()
