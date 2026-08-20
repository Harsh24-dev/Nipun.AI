"""Ask-back clarification — targeted, deterministic, and only when genuinely needed."""

from src.agents.clarify import assess_clarification


def test_farming_crop_query_without_details_asks_form():
    card = assess_clarification(
        query="what crops should I sow this season", domain="farming",
        intent="crop_suggestion", profile={},
    )
    assert card is not None
    assert card["cardType"] == "clarify"
    assert card["confidence"] == 1.0 and card["abstained"] is False
    names = {f["name"] for f in card["form"]["fields"]}
    # Location / land / soil are the details a good crop recommendation needs.
    assert {"location", "land_size", "soil_type"} & names


def test_farming_crop_query_satisfied_by_profile_does_not_ask():
    card = assess_clarification(
        query="what crops should I sow this season", domain="farming",
        intent="crop_suggestion",
        profile={"state": "Maharashtra", "land_size_acres": 5, "soil_type": "Black"},
    )
    assert card is None  # everything required is already known → answer directly


def test_finance_invest_without_amount_asks():
    card = assess_clarification(
        query="where should I invest to grow my money", domain="finance",
        intent="investment_advice", profile={},
    )
    assert card is not None
    assert len(card["form"]["fields"]) <= 4  # capped by CLARIFY_MAX_FIELDS


def test_finance_invest_fully_specified_does_not_ask():
    card = assess_clarification(
        query="I have 5 lakh to invest for 5 years with low risk", domain="finance",
        intent="investment_advice", profile={},
    )
    assert card is None  # amount + horizon + risk all present in the query


def test_general_query_never_asks():
    card = assess_clarification(
        query="who is the president of India", domain="governance",
        intent="factual", profile={},
    )
    assert card is None


def test_finance_loan_routes_to_loan_slots():
    card = assess_clarification(
        query="I need a loan for my business", domain="finance",
        intent="loan", profile={},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "loan_purpose" in names and "tenure" in names


def test_farming_pest_routes_to_pest_slots():
    card = assess_clarification(
        query="my cotton plants have yellow leaves and holes", domain="farming",
        intent="pest", profile={},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "symptom" in names


def test_student_learn_asks_level_and_depth():
    card = assess_clarification(
        query="I want to research machine learning", domain="student",
        intent="learn", profile={},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert {"level", "depth"} <= names  # research depth adapts to learner level


def test_scheme_eligibility_asks_demographics_not_in_profile():
    card = assess_clarification(
        query="which scheme am I eligible for", domain="scheme",
        intent="eligibility", profile={"age": 30, "gender": "Male"},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "age" not in names and "gender" not in names  # already known → not re-asked
    assert "category" in names or "annual_income" in names


def test_documents_query_asks_type_and_action():
    card = assess_clarification(
        query="I lost my PAN card", domain="documents", intent="document", profile={},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "document_type" in names and "action" in names


def test_informational_query_is_not_interrupted():
    # Definitional / how-to questions want an ANSWER, not a form.
    for q in ("what is a mutual fund", "explain crop rotation", "how does PM-KISAN work"):
        assert assess_clarification(q, domain="finance", intent="info", profile={}) is None or \
               assess_clarification(q, domain="farming", intent="info", profile={}) is None


def test_clarify_card_is_always_skippable():
    card = assess_clarification(
        query="what crops should I sow this season", domain="farming",
        intent="crop_suggestion", profile={},
    )
    assert card is not None
    assert card["form"]["allowSkip"] is True
    assert card["form"]["skipLabel"] in card["options"]  # a one-tap way forward always exists


def test_legal_query_asks_matter_and_stage():
    card = assess_clarification(
        query="my landlord is not returning my deposit, what are my rights",
        domain="legal", intent="advice", profile={},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "matter_type" in names


# ── Context-aware clarification: never re-ask what the user already told us ────────

def test_does_not_reask_details_answered_earlier_this_session():
    # The user answered a farming form on a prior turn; now they ask another crop question.
    answered = {"location": "Nashik", "land_size": "5 acres", "soil_type": "Black"}
    card = assess_clarification(
        query="what crops should I sow this season", domain="farming",
        intent="crop_suggestion", profile={}, answered=answered,
    )
    assert card is None  # all required details already given this conversation → don't re-ask


def test_does_not_reask_details_mentioned_in_conversation_history():
    # Details were stated in an earlier message, not a form.
    history = "I have a 5 acre farm in Nashik with black soil"
    card = assess_clarification(
        query="which crop is best for me now", domain="farming",
        intent="crop_suggestion", profile={}, history_text=history,
    )
    assert card is None


def test_partial_prior_answers_only_asks_whats_still_missing():
    # Location known from earlier; land + soil still unknown → ask only those.
    card = assess_clarification(
        query="what should I grow", domain="farming", intent="crop_suggestion",
        profile={}, answered={"location": "Nashik"},
    )
    assert card is not None
    names = {f["name"] for f in card["form"]["fields"]}
    assert "location" not in names                      # already known → not re-asked
    assert {"land_size", "soil_type"} & names           # still-missing details are asked
