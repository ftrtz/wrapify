"""
Serve both ETL and analytics flows in a single long-running process.

This script creates deployments for both flows and serves them together,
allowing them to be scheduled and triggered from the Prefect UI.
"""

from prefect import serve

from etl.analytics.flow import analytics_flow
from etl.flow import spotify_etl

if __name__ == "__main__":
    # Create deployment for main ETL flow
    etl_deployment = spotify_etl.to_deployment(
        name="spotify-etl",
        cron="0 * * * *",  # Run every hour
        tags=["production", "etl"],
        description="Extract Spotify listening data and load to database",
    )

    # Create deployment for analytics flow
    # Note: This can be triggered manually or via Prefect automation on "new-data" event
    analytics_deployment = analytics_flow.to_deployment(
        name="analytics-flow",
        tags=["production", "analytics"],
        description="Calculate listening statistics from raw data",
    )

    # Serve both flows in one process
    # This creates a long-running process that polls for scheduled/triggered runs
    serve(etl_deployment, analytics_deployment, pause_on_shutdown=False,)
