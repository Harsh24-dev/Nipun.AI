"""Tests for working memory (L0)."""

from src.memory.working import WorkingMemory, ConversationTurn


def test_append_and_get():
    wm = WorkingMemory(max_turns=5)
    wm.append("s1", ConversationTurn(role="user", content="hello", language="en"))
    wm.append("s1", ConversationTurn(role="assistant", content="hi there", language="en"))
    turns = wm.get("s1")
    assert len(turns) == 2
    assert turns[0].role == "user"
    assert turns[1].content == "hi there"


def test_fifo_eviction():
    wm = WorkingMemory(max_turns=3)
    for i in range(5):
        wm.append("s1", ConversationTurn(role="user", content=f"msg{i}", language="en"))
    turns = wm.get("s1")
    assert len(turns) == 3
    # Should have last 3 messages
    assert turns[0].content == "msg2"
    assert turns[-1].content == "msg4"


def test_clear():
    wm = WorkingMemory(max_turns=5)
    wm.append("s1", ConversationTurn(role="user", content="test", language="en"))
    wm.clear("s1")
    assert wm.get("s1") == []


def test_separate_sessions():
    wm = WorkingMemory(max_turns=5)
    wm.append("s1", ConversationTurn(role="user", content="session1", language="en"))
    wm.append("s2", ConversationTurn(role="user", content="session2", language="hi"))
    assert wm.get("s1")[0].content == "session1"
    assert wm.get("s2")[0].content == "session2"


def test_to_llm_messages():
    wm = WorkingMemory(max_turns=5)
    wm.append("s1", ConversationTurn(role="user", content="who are you", language="en"))
    wm.append("s1", ConversationTurn(role="assistant", content="I am Nipun.AI", language="en"))
    msgs = wm.to_llm_messages("s1")
    assert msgs == [
        {"role": "user", "content": "who are you"},
        {"role": "assistant", "content": "I am Nipun.AI"},
    ]


def test_remember_and_get_facts_merges_and_skips_empty():
    wm = WorkingMemory(max_turns=5)
    wm.remember_facts("s1", {"land_size": "5 acres", "soil_type": "", "_skipped": True})
    wm.remember_facts("s1", {"location": "Nashik"})
    facts = wm.get_facts("s1")
    assert facts == {"land_size": "5 acres", "location": "Nashik"}  # empties/control keys dropped
    # A later answer overwrites an earlier one (a correction sticks).
    wm.remember_facts("s1", {"land_size": "8 acres"})
    assert wm.get_facts("s1")["land_size"] == "8 acres"


def test_facts_are_session_scoped_and_cleared():
    wm = WorkingMemory(max_turns=5)
    wm.remember_facts("s1", {"occupation": "farmer"})
    assert wm.get_facts("s2") == {}          # never leaks across sessions
    wm.clear("s1")
    assert wm.get_facts("s1") == {}          # clear drops facts too


def test_recent_user_text_only_user_turns():
    wm = WorkingMemory(max_turns=10)
    wm.append("s1", ConversationTurn(role="user", content="I farm in Nashik", language="en"))
    wm.append("s1", ConversationTurn(role="assistant", content="Great!", language="en"))
    wm.append("s1", ConversationTurn(role="user", content="5 acres of black soil", language="en"))
    text = wm.recent_user_text("s1")
    assert "Nashik" in text and "black soil" in text
    assert "Great!" not in text            # assistant turns excluded
