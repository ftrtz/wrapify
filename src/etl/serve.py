"""
Serve both ETL and analytics flows with automatic analytics triggering.

This script:
1. Registers ETL and analytics flow deployments
2. Sets up automation to run analytics when insert_prod task completes
3. Serves both flows in a long-running process
"""

from prefect import serve
from prefect.automations import Automation
from prefect.events.schemas.automations import EventTrigger
from prefect.events.actions import RunDeployment
from prefect.settings import PREFECT_API_URL
import httpx
import time

from etl.analytics.flow import analytics_flow
from etl.flow import spotify_etl


def setup_automation():
    """Set up automation to trigger analytics when insert_prod completes."""
    # Check if automation already exists
    try:
        existing = Automation.read(name="analytics-on-insert-prod-completion")
        print(f"✓ Automation already configured: analytics-flow runs when insert_prod completes")
        return
    except Exception:
        pass

    # Wait briefly for deployments to be registered
    print("Setting up automation...")
    time.sleep(2)

    # Get analytics deployment ID
    try:
        response = httpx.post(
            f"{PREFECT_API_URL.value()}/deployments/filter",
            json={"deployments": {"name": {"any_": ["analytics-flow"]}}, "limit": 1},
            timeout=10.0,
        )

        if response.status_code != 200 or not (deployments := response.json()):
            print("⚠ Could not find analytics-flow deployment yet - automation not created")
            print("  Run 'uv run python -m etl.setup_automation' after serve starts")
            return

        deployment_id = deployments[0]["id"]

        # Create automation with wildcard to match task names like "insert_prod-603"
        automation = Automation(
            name="analytics-on-insert-prod-completion",
            description="Run analytics when ETL insert_prod task completes",
            enabled=True,
            trigger=EventTrigger(
                expect={"prefect.task-run.Completed"},
                match={"prefect.resource.name": "insert_prod*"},
                posture="Reactive",
                threshold=1,
                within=0,
            ),
            actions=[RunDeployment(source="selected", deployment_id=deployment_id)],
        )

        created = automation.create()
        print(f"✓ Created automation to run analytics-flow when insert_prod task completes")
        print(f"  Automation ID: {created.id}")
    except Exception as e:
        print(f"⚠ Could not create automation: {e}")
        print("  Run 'uv run python -m etl.setup_automation' manually after serve starts")


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

    # Set up automation before serving
    setup_automation()

    # Serve both flows in one process
    print("\nServing flows...")
    serve(etl_deployment, analytics_deployment, pause_on_shutdown=False)
