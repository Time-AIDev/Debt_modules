"""The Odoo door hands normalise() crm.lead rows by field name (the file door went
2026-09-25)."""
import pytest

from app.pipelines import ingress, rules as rules_mod

RULES = rules_mod.load()


class FakeExecute:
    """Stands in for odoo._execute: leads with ids 1..total, answered by the keyset
    domain [("id", ">", n)] ordered by id. Records what was asked for; `on_page`
    lets a test change Odoo between two pages."""

    def __init__(self, total=1200):
        self.ids = list(range(1, total + 1))
        self.calls, self.on_page = [], None

    def __call__(self, config, uid, model, method, args, kwargs=None):
        self.calls.append((model, method, args, kwargs or {}))
        if method == "search_count":
            return len(self.ids)
        after = dict((f, v) for f, _op, v in args[0]).get("id", 0)
        page = [{"id": i, "volt_id": "VL%07d" % i}
                for i in self.ids if i > after][:(kwargs or {}).get("limit", 500)]
        if self.on_page:
            self.on_page(self)
        return page


def test_the_pull_pages_by_id_rather_than_asking_for_everything_at_once(monkeypatch):
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1200)
    rows = ingress.from_odoo(RULES, execute=fake)
    assert len(rows) == 1200
    reads = [c for c in fake.calls if c[1] == "search_read"]
    # keyset, not offsets: each page asks for the ids after the last one it saw, until
    # a page comes back empty
    expected = ingress.ELIGIBILITY_DOMAIN
    assert [c[2] for c in reads] == [[expected + [("id", ">", n)]] for n in (0, 500, 1000, 1200)]
    assert all(c[3]["limit"] == ingress.PAGE and c[3]["order"] == "id" and "offset" not in c[3]
               for c in reads)


def test_the_pull_filters_to_won_installed_leads_at_odoo(monkeypatch):
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1)
    ingress.from_odoo(RULES, execute=fake)
    calls = [c for c in fake.calls if c[1] == "search_read"]
    assert calls
    assert all(("stage_name", "=", "Won") in c[2][0] for c in calls)
    assert all(("epc_start_date", "!=", False) in c[2][0] for c in calls)
    assert all(("epc_end_date", "!=", False) in c[2][0] for c in calls)


def test_a_lead_deleted_mid_pull_does_not_hide_a_live_one(monkeypatch):
    """With offsets, Odoo deleting lead 10 and creating lead 1201 between two pages
    shifted every later row back one: lead 501 fell between the pages, the count
    still matched, and the complete pull retired a live lead."""
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1200)

    def churn(odoo):
        if 10 in odoo.ids:
            odoo.ids.remove(10)
            odoo.ids.append(1201)
    fake.on_page = churn
    ids = {r["id"] for r in ingress.from_odoo(RULES, execute=fake)}
    assert 501 in ids and 1201 in ids


def test_a_lead_odoo_deletes_mid_pull_does_not_fail_a_complete_pull(monkeypatch):
    """2026-09-25, the first live pull on this code: Odoo counted 34,670 leads, one
    was deleted during the minute-long read, and the run failed as "short" although it
    had read every lead that still existed."""
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1200)

    def delete_an_unread_lead(odoo):
        if 700 in odoo.ids:
            odoo.ids.remove(700)
    fake.on_page = delete_an_unread_lead
    ids = {r["id"] for r in ingress.from_odoo(RULES, execute=fake)}
    assert len(ids) == 1199 and 700 not in ids


def test_the_field_list_comes_from_the_rules_not_from_a_constant(monkeypatch):
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1)
    ingress.from_odoo(RULES, execute=fake)
    asked = [c for c in fake.calls if c[1] == "search_read"][0][3]["fields"]
    mapped = {r["crm.lead field"] for r in RULES.field_map
              if r["crm.lead field"] not in ("—", "id")}
    assert mapped <= set(asked)


def test_a_pull_shorter_than_odoo_counted_fails_rather_than_retiring_the_tail(monkeypatch):
    """A complete pull retires every lead it did not see, so a short page (Odoo
    answered 1,200 in its count and stopped at 1,000) must fail the run."""
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1000)
    real = fake.__call__

    def counts_more(config, uid, model, method, args, kwargs=None):
        return 1200 if method == "search_count" else real(config, uid, model, method, args, kwargs)
    with pytest.raises(ingress.odoo.OdooError):
        ingress.from_odoo(RULES, execute=counts_more)


def test_the_pull_reports_its_progress_page_by_page(monkeypatch):
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    seen = []
    fake = FakeExecute(total=1200)
    ingress.from_odoo(RULES, execute=fake, on_progress=lambda **kw: seen.append(kw))
    assert seen == [{"read": 500, "total": 1200},
                    {"read": 1000, "total": 1200},
                    {"read": 1200, "total": 1200}]


def test_the_pull_reports_mutually_exclusive_eligibility_exclusions(monkeypatch):
    monkeypatch.setattr(ingress.odoo, "_config", lambda: {})
    monkeypatch.setattr(ingress.odoo, "_login", lambda config: 1)
    fake = FakeExecute(total=1)
    seen = []
    ingress.from_odoo(RULES, execute=fake, on_exclusions=lambda counts: seen.append(counts))
    assert seen == [{
        "not_won": 1,
        "install_start_missing": 1,
        "install_end_missing": 1,
    }]
