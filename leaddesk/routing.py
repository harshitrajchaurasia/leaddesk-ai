from .models import Client, DisputeVerdict, Route, Triage

CONFIDENCE_MIN = 0.7
CHURN_MIN = 0.7

CATEGORY_QUEUE = {
    "billing": "billing",
    "campaign_change": "campaign_ops",
    "appointments": "account_manager",
    "tech_access": "support",
    "other": "human_review",
}


def route(triage: Triage, verdict: DisputeVerdict | None, client: Client) -> Route:
    am = client.account_manager
    # Churn first: an at-risk client goes to their account manager even when the category is unclear,
    # because missing a cancellation costs more than a misrouted ticket.
    if triage.churn_risk >= CHURN_MIN:
        return Route(queue="account_manager", priority="urgent", assignee=am, reasons=[f"churn risk {triage.churn_risk:.2f}"])
    if triage.confidence < CONFIDENCE_MIN:
        return Route(queue="human_review", priority=triage.urgency, reasons=[f"low confidence {triage.confidence:.2f}"])
    if triage.category == "cancellation":
        return Route(queue="account_manager", priority="urgent", assignee=am, reasons=["cancellation intent"])
    if triage.category == "lead_quality":
        if verdict is not None and verdict.verdict == "VALID_COACH":
            return Route(queue="account_manager", priority=triage.urgency, assignee=am, reasons=["coach agent"])
        return Route(queue="lead_ops", priority=triage.urgency, reasons=["lead dispute"])
    queue = CATEGORY_QUEUE[triage.category]
    return Route(queue=queue, priority=triage.urgency, assignee=am if queue == "account_manager" else None,
                 reasons=[f"category {triage.category}"])
