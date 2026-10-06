"""A restore readiness probe must never run copied production jobs."""
import asyncio
import pytest
from app import durable_schedule, local_worker, object_retention


@pytest.mark.parametrize("environment,flag", [("prd", "true"), ("production", "true"),
                                             ("stg", "false"), ("dev", "true")])
def test_probe_mode_refuses_normal_and_production_profiles(monkeypatch, environment, flag):
    monkeypatch.setenv("ENV", environment)
    monkeypatch.setenv("VOLT_RECOVERY_READ_ONLY", flag)
    with pytest.raises(RuntimeError, match="isolated staging"):
        asyncio.run(local_worker.serve(probe_only=True))


def test_isolated_restore_probe_updates_heartbeat_without_claim_or_cleanup(monkeypatch):
    monkeypatch.setenv("ENV", "stg")
    monkeypatch.setenv("VOLT_RECOVERY_READ_ONLY", "true")
    monkeypatch.setenv("TASK_QUEUE_BACKEND", "postgres")
    ticks = []
    monkeypatch.setattr(local_worker, "heartbeat", lambda state, uid=None: ticks.append(state))
    monkeypatch.setattr(durable_schedule, "enqueue_due", lambda: pytest.fail("must not enqueue copied schedule"))
    monkeypatch.setattr(object_retention, "cleanup", lambda **kwargs: pytest.fail("must not remove restored objects"))
    async def claim(): pytest.fail("must not execute copied jobs")
    async def stop(_seconds): raise asyncio.CancelledError
    monkeypatch.setattr(local_worker, "run_once", claim)
    monkeypatch.setattr(local_worker.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(local_worker.serve(probe_only=True))
    assert ticks == ["idle"]
