"""
Serve both ETL and analytics flows with automatic analytics triggering.

This script:
1. Registers ETL and analytics flow deployments
2. Sets up automation to run analytics when insert_prod task completes
3. Serves both flows in a long-running process
"""

from prefect import serve

from etl.analytics.flow import analytics_flow
from etl.flow import spotify_etl
from etl.setup_automation import setup_automation

if __name__ == "__main__":
    # Create deployment for main ETL flow
    etl_deployment = spotify_etl.to_deployment(
        name="spotify-etl",
        cron="0 * * * *",  # Run every hour
        tags=["production", "etl"],
        description="Extract Spotify listening data and load to database",
    )

    # Create deployment for analytics flow
    analytics_deployment = analytics_flow.to_deployment(
        name="analytics-flow",
        tags=["production", "analytics"],
        description="Calculate listening statistics from raw data",
    )

    # Register the analytics deployment up front so the automation can bind to a
    # real deployment ID. to_deployment() only builds an object in memory -
    # without this, the automation would be wired to whatever was registered by
    # a previous run (or nothing at all on a first start). apply() upserts, so
    # serve() below reuses the same deployment.
    try:
        setup_automation(analytics_deployment.apply())
    except Exception as e:
        print(f"⚠ Could not register analytics deployment for automation: {e}")
        print("  Run 'uv run python -m etl.setup_automation' after serve starts")

    # Serve both flows in one process
    print("\nServing flows...")
    serve(etl_deployment, analytics_deployment, pause_on_shutdown=False)
