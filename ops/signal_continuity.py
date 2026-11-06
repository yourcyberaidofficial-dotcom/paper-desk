"""Observation, research, and execution are separate facts.

A failed study does not delete an observation. An AutoPilot rejection does
not delete a signal. This module does not fetch a price and does not invent one.
"""

from __future__ import annotations

OBSERVATIONS = frozenset({
    "market_observation",
    "forming",
    "active_signal",
    "invalidated",
    "expired",
    "data_unavailable",
})


def classify_card(card):
    """Label one existing card. Missing prices stay missing."""
    card = card or {}
    quality = card.get("quality")
    decision = card.get("decision")
    reading = card.get("reading_class")
    customer = card.get("customer_status")
    if card.get("lifecycle") == "invalidated" or card.get("state") == "invalidated":
        observation = "invalidated"
    elif card.get("lifecycle") == "expired" or card.get("state") == "expired":
        observation = "expired"
    elif customer == "reading_unavailable" or quality in {None, "unavailable", "unlicensed"} or reading == "unavailable":
        observation = "data_unavailable"
    elif reading == "developing" or card.get("setup_state") == "forming" or card.get("decision_label") == "WATCH":
        observation = "forming"
    elif decision in {"BUY", "SELL"} and card.get("entry") is not None and card.get("stop") is not None and card.get("target") is not None:
        observation = "active_signal"
    else:
        observation = "market_observation"
    if card.get("approved") is True:
        research = "approved"
    elif card.get("validation_status") in {"FAIL", "FAILED", "BLOCKED", "REJECTED"} or card.get("research_status") in {"FAIL", "FAILED"}:
        research = "research_failed"
    else:
        research = "not_promoted"
    if card.get("autopilot_eligible") is True and card.get("approved") is True:
        execution = "autopilot_eligible"
    elif card.get("manual_paper") is True or card.get("provenance") == "user_authored":
        execution = "paper_eligible"
    else:
        execution = "not_eligible"
    released = observation != "data_unavailable"
    return {
        "symbol": card.get("symbol"),
        "interval": card.get("interval"),
        "observation": observation if observation in OBSERVATIONS else "data_unavailable",
        "research": research,
        "execution": execution,
        "decision": decision if released else "WAIT",
        "price": card.get("price") if released else None,
        "entry": card.get("entry") if released else None,
        "stop": card.get("stop") if released else None,
        "target": card.get("target") if released else None,
        "source_id": card.get("source_id") if released else None,
        "opportunity_id": card.get("opportunity_id"),
        "note": _note(observation, research, execution),
    }


def _note(observation, research, execution):
    if observation == "data_unavailable":
        return "No authorised reading. Research status is separate and did not remove a price, because none was released."
    if research == "research_failed":
        return "The observation remains. The study did not pass research, so it is not an approved strategy."
    if execution == "not_eligible":
        return "The observation remains. AutoPilot cannot open it."
    if execution == "paper_eligible":
        return "Eligible for a manual paper plan. Not an AutoPilot order."
    return "The observation remains."
