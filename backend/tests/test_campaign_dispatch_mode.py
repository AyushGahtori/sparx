from types import SimpleNamespace

from app.models.firestore_documents import CampaignDocument
from app.services.campaign_runner_service import CampaignRunnerService


def build_campaign(*, dispatch_mode: str = "parallel") -> CampaignDocument:
    return CampaignDocument(
        campaign_id="campaign_test",
        campaign_name="Test Campaign",
        agent_id="agent_1",
        agent_name="Agent One",
        campaign_type="outbound",
        call_objective="Book meetings for the product demo.",
        language="English",
        priority="high",
        schedule_type="immediate",
        dispatch_mode=dispatch_mode,
    )


def build_runner(max_parallel_calls: int = 3) -> CampaignRunnerService:
    return CampaignRunnerService(
        settings=SimpleNamespace(
            campaign_max_parallel_calls=max_parallel_calls,
            campaign_dispatch_interval_seconds=8,
            queue_recovery_stale_seconds=300,
            resolved_run_background_runners=True,
        ),
        campaign_repository=None,
        contact_repository=None,
        call_service=None,
        sync_service=None,
    )


def test_campaign_dispatch_mode_defaults_to_parallel():
    campaign = build_campaign()
    runner = build_runner(max_parallel_calls=4)

    assert runner._resolve_dispatch_mode(campaign) == "parallel"
    assert runner._resolve_parallel_call_limit(campaign) == 4


def test_campaign_dispatch_mode_one_by_one_limits_parallel_capacity():
    campaign = build_campaign(dispatch_mode="one_by_one")
    runner = build_runner(max_parallel_calls=4)

    assert runner._resolve_dispatch_mode(campaign) == "one_by_one"
    assert runner._resolve_parallel_call_limit(campaign) == 1
