# -*- coding: utf-8 -*-
"""The shipped Master Note cards are data, so they get validated like data.

A malformed card does not crash anything — it silently narrows the analysis by dropping a
question nobody notices is gone.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

CARD_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "master-notes"
CARDS = sorted(CARD_DIR.glob("*.json"))

#: The dimension keys each framework must offer, from HARNESS.md section 5.
EXPECTED_DIMENSIONS = {
    "MN02": {
        "capability", "product_solution", "industry", "market_opportunity",
        "tpm_alignment", "market_risk", "product_risk", "route_risk",
    },
    "MN03": {
        "user", "buyer", "customer", "problem", "problem_severity", "kbf",
        "customer_touchpoint",
    },
    "MN04": {
        "competitor", "substitute", "comparison_criteria", "competitive_advantage",
        "value_proposition", "positioning",
    },
    "MN05": {
        "channel", "customer_relationship", "resource", "activity", "partner",
        "bm_alignment",
    },
    "MN06": {"cost", "price", "margin", "channel_cost", "revenue_model", "pricing_structure"},
    "MN07": {
        "feasibility", "sales_quantity", "price_times_quantity", "estimated_profit",
        "valid_market", "scalability",
    },
}


def _load(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_expected_cards_are_present() -> None:
    assert {p.stem for p in CARDS} == set(EXPECTED_DIMENSIONS)


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.stem)
def test_card_shape(path: Path) -> None:
    card = _load(path)

    assert card["framework_id"] == path.stem, "filename and framework_id must agree"
    assert card["title_ko"] and card["title_en"], "both languages are required"
    assert card["dimensions"], "a framework with no dimensions asks no questions"

    keys = [d["key"] for d in card["dimensions"]]
    assert len(keys) == len(set(keys)), f"duplicate dimension keys: {keys}"

    for dimension in card["dimensions"]:
        assert dimension["label_ko"] and dimension["label_en"]
        assert dimension.get("question_ko"), f"{dimension['key']}: missing question_ko"
        assert dimension.get("question_en"), f"{dimension['key']}: missing question_en"


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.stem)
def test_card_covers_the_documented_dimensions(path: Path) -> None:
    card = _load(path)
    keys = {d["key"] for d in card["dimensions"]}
    expected = EXPECTED_DIMENSIONS[card["framework_id"]]

    assert keys == expected, (
        f"{path.stem} drifted from HARNESS.md section 5. "
        f"Missing: {sorted(expected - keys)}. Unexpected: {sorted(keys - expected)}."
    )


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.stem)
def test_card_points_at_the_handbook_instead_of_copying_it(path: Path) -> None:
    """The reference is a pointer. Duplicated methodology text drifts and misleads."""
    reference = _load(path).get("reference", {})
    assert reference.get("handbook_chapter"), "each card names its handbook chapter"
    assert reference.get("handbook_paths"), "each card lists the paths to read"

    for value in reference.values():
        text = value if isinstance(value, str) else ""
        assert len(text) < 200, (
            f"{path.stem}: reference entry looks like copied prose rather than a pointer"
        )


@pytest.mark.parametrize("path", CARDS, ids=lambda p: p.stem)
def test_cards_stay_framework_only(path: Path) -> None:
    """A card states what to check. It must not assert facts about a market or a company.

    This is the boundary that keeps the harness honest (HARNESS.md section 5) and it is also a
    publication rule: this repository is public.
    """
    card = _load(path)
    questions = [
        q
        for dimension in card["dimensions"]
        for q in (dimension.get("question_ko"), dimension.get("question_en"))
        if q
    ]
    assert questions

    for question in questions:
        assert "?" in question, (
            f"{path.stem}: {question!r} is not phrased as a question, which is how a "
            "framework turns into an assertion"
        )
