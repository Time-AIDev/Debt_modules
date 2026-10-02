"""The debt-crm-lead-sync Cloud Run Job: exit 2 not configured, 1 refused, 0 synced.

The job is the durable copy of the in-process 15-minute refetch — Cloud Run scales
to zero, so a daemon thread in the service cannot promise a cadence.
"""
from app.jobs import crm_lead_sync


def test_no_database_is_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(crm_lead_sync.db, "configured", lambda: False)
    assert crm_lead_sync.main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_odoo_not_configured_is_exit_2(monkeypatch, capsys):
    monkeypatch.setattr(crm_lead_sync.db, "configured", lambda: True)
    monkeypatch.setattr(crm_lead_sync.schedule, "odoo_ready", lambda: False)
    assert crm_lead_sync.main() == 2
    assert "not configured" in capsys.readouterr().err


def test_a_failed_pull_is_exit_1(monkeypatch, capsys):
    monkeypatch.setattr(crm_lead_sync.db, "configured", lambda: True)
    monkeypatch.setattr(crm_lead_sync.schedule, "odoo_ready", lambda: True)
    monkeypatch.setattr(crm_lead_sync.service, "run_odoo",
                        lambda mode=None: {"state": "failed", "problem": {"code": "integration_unavailable"}})
    assert crm_lead_sync.main() == 1
    assert "integration_unavailable" in capsys.readouterr().err


def test_a_good_pull_lands_then_tells_the_process(monkeypatch, capsys):
    """The pull itself rebinds the book and bumps the epoch (service._land ->
    refresh.after_landing, only when something changed); the job no longer does it a
    second time, which built the book three times per run."""
    from app import refresh

    monkeypatch.setattr(crm_lead_sync.db, "configured", lambda: True)
    monkeypatch.setattr(crm_lead_sync.schedule, "odoo_ready", lambda: True)
    monkeypatch.setattr(crm_lead_sync.service, "run_odoo",
                        lambda mode=None: {"state": "done", "run_id": 41, "landed": 12, "new": 9,
                                           "changed": 3, "unchanged": 34008, "retired": 2, "rejected": 138})
    seen = []
    monkeypatch.setattr(refresh, "after_landing",
                        lambda kind, run_id=None, changed=True: seen.append((kind, run_id)) or {"served": True})
    assert crm_lead_sync.main() == 0
    assert seen == []
    out = capsys.readouterr().out
    assert "landed=12 new=9 changed=3 unchanged=34008 retired=2 rejected=138" in out
