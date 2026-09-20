"""
Create or reconcile the automation that triggers analytics after the ETL loads
new data.

The automation's RunDeployment action stores a deployment ID. If the
analytics-flow deployment is ever recreated (server database reset, flow
renamed, deployment deleted in the UI), that stored ID goes stale and the
automation silently fires at a deployment that returns 404 - the event matches,
but no flow run is ever created.

To avoid that, `setup_automation` reconciles on every startup instead of
bailing out when an automation with the same name already exists.

Run standalone to repair the automation without restarting the serve process:

    uv run python -m etl.setup_automation
"""

from uuid import UUID

from prefect.automations import Automation
from prefect.client.orchestration import get_client
from prefect.events.actions import RunDeployment
from prefect.events.schemas.automations import EventTrigger
from prefect.exceptions import ObjectNotFound

AUTOMATION_NAME = "analytics-on-insert-prod-completion"
AUTOMATION_DESCRIPTION = "Run analytics when ETL insert_prod task completes"
ANALYTICS_DEPLOYMENT_NAME = "analytics-flow/analytics-flow"


def build_trigger() -> EventTrigger:
    """Fire when an insert_prod task run completes.

    The wildcard matches Prefect's random task name suffixes (e.g.
    "insert_prod-a8c"). insert_prod only runs when the ETL found new data, so
    matching it keeps analytics from recalculating on empty runs.
    """
    return EventTrigger(
        expect={"prefect.task-run.Completed"},
        match={"prefect.resource.name": "insert_prod*"},
        posture="Reactive",
        threshold=1,
        within=0,
    )


def find_analytics_deployment_id() -> UUID | None:
    """Look up the current analytics-flow deployment ID."""
    try:
        with get_client(sync_client=True) as client:
            return client.read_deployment_by_name(ANALYTICS_DEPLOYMENT_NAME).id
    except ObjectNotFound:
        print(f"⚠ Deployment '{ANALYTICS_DEPLOYMENT_NAME}' not found")
        return None
    except Exception as e:
        print(f"⚠ Could not look up analytics deployment: {e}")
        return None


def setup_automation(deployment_id: UUID) -> None:
    """Point the analytics automation at `deployment_id`, creating it if absent.

    Safe to call on every startup: it only writes when the stored action has
    drifted from the deployment currently being served.
    """
    action = RunDeployment(source="selected", deployment_id=deployment_id)

    try:
        existing = Automation.read(name=AUTOMATION_NAME)
    except ValueError:
        existing = None
    except Exception as e:
        print(f"⚠ Could not read existing automations: {e}")
        print("  Run 'uv run python -m etl.setup_automation' to retry")
        return

    if existing is None:
        try:
            created = Automation(
                name=AUTOMATION_NAME,
                description=AUTOMATION_DESCRIPTION,
                enabled=True,
                trigger=build_trigger(),
                actions=[action],
            ).create()
            print("✓ Created automation to run analytics-flow when insert_prod completes")
            print(f"  Automation ID: {created.id}")
        except Exception as e:
            print(f"⚠ Could not create automation: {e}")
            print("  Run 'uv run python -m etl.setup_automation' to retry")
        return

    stored_ids = [getattr(a, "deployment_id", None) for a in existing.actions]
    if stored_ids == [deployment_id] and existing.enabled:
        print("✓ Automation already points at the current analytics-flow deployment")
        return

    # Drifted (stale deployment ID, hand-edited action, or disabled) - rewrite it.
    existing.trigger = build_trigger()
    existing.actions = [action]
    existing.enabled = True
    try:
        existing.update()
        print(f"✓ Updated automation '{AUTOMATION_NAME}'")
        print(f"  Was targeting: {stored_ids}")
        print(f"  Now targeting: {deployment_id}")
    except Exception as e:
        print(f"⚠ Could not update automation: {e}")
        print("  Run 'uv run python -m etl.setup_automation' to retry")


if __name__ == "__main__":
    if (deployment_id := find_analytics_deployment_id()) is None:
        print("  Start the serve process first so the deployment is registered.")
        raise SystemExit(1)
    setup_automation(deployment_id)
