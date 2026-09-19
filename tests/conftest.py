import pytest

from brownie_agent import chat_model


@pytest.fixture(autouse=True)
def isolate_model_configuration(monkeypatch, tmp_path):
    """Tests never use local credentials, model lists, or persistent quota state."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    for role in ("TEXT", "STEERING"):
        for suffix in ("", "_API_KEY", "_BASE_URL", "_FALLBACKS"):
            monkeypatch.delenv(role + "_MODEL" + suffix, raising=False)
    monkeypatch.setattr(chat_model, "COOLDOWNS", chat_model.Cooldowns(tmp_path / "cooldowns.json"))
