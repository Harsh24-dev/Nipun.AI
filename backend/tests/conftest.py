import pytest


@pytest.fixture
def mock_settings(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-at-least-32-characters")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-jwt-key-at-least-32-characters!!")
    monkeypatch.setenv("POSTGRES_PASSWORD", "testpassword")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "openai")
