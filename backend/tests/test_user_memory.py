"""Long-term memory — extraction cleaning + prompt formatting (pure, offline)."""

from src.agents.memory_extractor import _clean_memories, _clean_profile, _new_profile_facts
from src.memory.user_memory import format_for_prompt


def test_clean_profile_whitelists_and_coerces():
    raw = {
        "state": "Maharashtra", "district": "Nashik", "occupation": " farmer ",
        "land_size_acres": "5", "current_crops": ["cotton", " ", "soybean"],
        "soil_type": "Black", "unknown_key": "ignored", "age": 30,   # age not learnable here
    }
    out = _clean_profile(raw)
    assert out["state"] == "Maharashtra"
    assert out["occupation"] == "farmer"               # trimmed
    assert out["land_size_acres"] == 5.0               # numeric coercion
    assert out["current_crops"] == ["cotton", "soybean"]  # blanks dropped
    assert "unknown_key" not in out and "age" not in out   # non-whitelisted dropped


def test_clean_memories_accepts_strings_and_dicts_and_caps():
    raw = [
        "Preparing for UPSC 2026",
        {"content": "Runs a dairy business", "kind": "context"},
        {"content": "x", "kind": "fact"},              # too short → dropped
        {"content": "Prefers Hindi", "kind": "weird"},  # bad kind → normalized to 'fact'
        12345,                                          # non-str/dict → dropped
    ]
    out = _clean_memories(raw)
    contents = [m["content"] for m in out]
    assert "Preparing for UPSC 2026" in contents
    assert {"content": "Runs a dairy business", "kind": "context"} in out
    assert all(len(m["content"]) >= 3 for m in out)
    assert next(m for m in out if m["content"] == "Prefers Hindi")["kind"] == "fact"


def test_new_profile_facts_only_returns_novelty():
    existing = {"state": "Maharashtra", "current_crops": ["cotton"]}
    facts = {"state": "Karnataka", "district": "Nashik", "current_crops": ["cotton", "wheat"]}
    new = _new_profile_facts(facts, existing)
    assert "state" not in new                    # already known scalar → not overwritten here
    assert new["district"] == "Nashik"           # genuinely new scalar
    assert new["current_crops"] == ["wheat"]     # only the new array item


def test_format_for_prompt_empty_and_populated():
    assert format_for_prompt([]) == ""
    assert format_for_prompt([{"content": ""}]) == ""
    block = format_for_prompt([{"content": "Runs a dairy"}, {"content": "Prefers Hindi"}])
    assert "Runs a dairy" in block and "Prefers Hindi" in block
    assert "REMEMBER ABOUT THIS USER" in block
