"""Shopping product-finder — ranking, platform trust, and buy-ready comparison cards."""

from src.agents.clarify import assess_clarification
from src.mcp.live.shopping import (
    _parse_price,
    _parse_rating,
    _platform_for,
    build_shopping_card,
    rank_products,
)


def test_platform_detection_and_reasons():
    amazon = _platform_for("https://www.amazon.in/dp/B0XYZ")
    assert amazon and amazon["name"] == "Amazon India" and "return" in amazon["why"].lower()
    assert _platform_for("https://randomblog.com/review") is None


def test_price_and_rating_extraction():
    assert _parse_price("Now at ₹19,999 only") == 19999
    assert _parse_price("Rs 1,250 with offer") == 1250
    assert _parse_price("no price here") is None
    assert _parse_rating("rated 4.3 out of 5") == 4.3
    assert _parse_rating("4.5 stars") == 4.5


def test_ranking_prefers_in_budget_then_rating_then_price():
    results = [
        {"title": "Phone A", "url": "https://amazon.in/a", "content": "₹25,000 rated 4.2 out of 5"},
        {"title": "Phone B", "url": "https://flipkart.com/b", "content": "₹18,000 rated 4.6 out of 5"},
        {"title": "Phone C", "url": "https://blog.com/c", "content": "great phone"},   # no platform → dropped
    ]
    ranked = rank_products(results, budget=20000)
    assert [o["platform"] for o in ranked] == ["Flipkart", "Amazon India"]  # B in-budget+higher rating first
    assert all("blog" not in o["url"] for o in ranked)  # non-retail reference excluded
    assert ranked[0]["why_platform"]  # every option explains why that platform


def test_build_card_has_working_links_and_reasons():
    ranked = rank_products(
        [{"title": "Washing Machine X", "url": "https://croma.com/x", "content": "₹22,990 4.4 out of 5"}],
        budget=25000,
    )
    card = build_shopping_card("washing machine", ranked, price_history_note="check sale events")
    assert card["cardType"] == "comparison_table"
    assert "Buy" in card["plan_cols"] and "Why here" in card["plan_cols"]
    assert card["plan_rows"][0]["Buy"].startswith("https://")   # working buy link
    assert card["sources"][0]["url"].startswith("https://")
    assert "card" in card["disclaimer"].lower()   # never asks for card/OTP


def test_shopping_query_triggers_clarification():
    card = assess_clarification(
        query="which phone should I buy", domain="general", intent="shopping", profile={},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "budget" in names
