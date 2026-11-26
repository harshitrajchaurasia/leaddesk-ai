import json

import pytest
from conftest import make_triage

from leaddesk import config
from leaddesk.routing import route


def test_shipped_rules_load():
    r = config.load()
    assert r.sla_minutes["urgent"] < r.sla_minutes["normal"] and r.queue_owners["lead_ops"]


@pytest.mark.parametrize("change", [
    lambda d: d.update(churn_min=1.5),                                  # out of range
    lambda d: d["category_queue"].update(billing="bilin"),               # typo in a queue name
    lambda d: d["sla_minutes"].pop("urgent"),                            # missing SLA
    lambda d: d["category_queue"].pop("other"),                          # unrouted category
])
def test_bad_rules_fail_loudly(tmp_path, change):
    d = json.loads(config.PATH.read_text())
    change(d)
    (tmp_path / "rules.json").write_text(json.dumps(d))
    with pytest.raises(ValueError):
        config.load(tmp_path / "rules.json")


def test_every_route_has_owner_and_sla(annuity_client):
    billing = route(make_triage(category="billing", urgency="high"), None, annuity_client)
    assert billing.assignee == config.RULES.queue_owners["billing"] and billing.sla_minutes == config.RULES.sla_minutes["high"]
    churn = route(make_triage(category="billing", churn_risk=0.9), None, annuity_client)
    assert churn.assignee == "Priya Shah" and churn.sla_minutes == config.RULES.sla_minutes["urgent"]
