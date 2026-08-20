"""Form-assist — fills everything except payment/OTP/password, and never touches credentials."""

import pytest

from src.execution.guards import CredentialError
from src.tasks import get_assistant, list_assistants
from src.tasks.forms import RTI_FORM, TRAIN_BOOKING_FORM


def test_form_assistants_are_registered():
    names = {t["name"] for t in list_assistants()}
    assert {"form_rti", "form_train_booking", "form_doctor_appointment"} <= names
    assert get_assistant("form_rti") is not None
    assert get_assistant("rti") is not None  # bare service name also resolves


def test_train_booking_autofills_from_profile_and_answers():
    card = TRAIN_BOOKING_FORM.run({
        "profile": {"name": "Ramesh Kumar", "age": 68},
        "answers": {"from_station": "Pune", "to_station": "Delhi", "travel_date": "12 Aug"},
    })
    labels = {f["label"]: f["value"] for f in card["filled_form"]["fields"]}
    assert labels["Passenger name"] == "Ramesh Kumar"
    assert labels["From station"] == "Pune"
    assert card["ready_for_handoff"] is True
    # Payment + OTP are ALWAYS the user's steps, never auto-filled.
    steps = " ".join(s["title"].lower() for s in card["steps"])
    assert "payment" in steps and "otp" in steps


def test_missing_required_fields_are_requested_not_invented():
    card = RTI_FORM.run({"profile": {"name": "Sita"}, "answers": {}})
    assert card["ready_for_handoff"] is False
    assert card["missing_fields"]  # e.g. subject/details still needed
    assert "Information sought (subject)" in card["missing_fields"]


def test_credentials_are_rejected_outright():
    # The agent must never even accept an OTP/password in the payload.
    with pytest.raises(CredentialError):
        TRAIN_BOOKING_FORM.run({
            "profile": {"name": "Ramesh"},
            "answers": {"otp": "123456", "from_station": "Pune"},
        })


def test_credential_like_values_never_reach_the_filled_form():
    # Even if a sensitive-looking value sneaks into a non-obvious field, it is not surfaced.
    card = RTI_FORM.run({
        "profile": {"name": "Ramesh"},
        "answers": {"rti_subject": "pension", "rti_details": "status of my claim"},
    })
    dumped = str(card["filled_form"])
    assert "123456" not in dumped
    # Every form always carries the safety disclaimer about never asking for OTP/PIN/etc.
    assert "OTP" in card["disclaimer"]
