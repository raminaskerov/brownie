
import pytest

from brownie_agent import config, launcher
from brownie_agent.settings import provider_status, save_provider_keys, validate_provider_settings


def test_packaged_windows_runtime_uses_local_app_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert config.default_ui_runtime_dir() == tmp_path / "Brownie"


def test_frozen_worker_relaunches_same_executable(monkeypatch):
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "executable", r"C:\Brownie\Brownie.exe")

    assert launcher.worker_command() == [r"C:\Brownie\Brownie.exe", "--brownie-worker"]


def test_saved_keys_preserve_other_env_settings(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("TEXT_MODEL=custom-model\nUNKNOWN=value\n", encoding="utf-8")

    status = save_provider_keys(tmp_path, {
        "typesafe_api_key": "typesafe-secret",
        "gemini_api_key": "gemini-secret",
    })

    saved = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "TEXT_MODEL=custom-model" in saved
    assert "UNKNOWN=value" in saved
    assert "TYPESAFE_API_KEY=typesafe-secret" in saved
    assert "GEMINI_API_KEY=gemini-secret" in saved
    assert status == {"jev_configured": True, "llm_configured": True, "text_configured": True}


def test_provider_status_never_returns_key_values(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=private\n", encoding="utf-8")

    assert provider_status(tmp_path) == {
        "jev_configured": True,
        "llm_configured": False,
        "text_configured": False,
    }


def test_search_explains_both_required_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValueError, match="TypeSafe"):
        validate_provider_settings(tmp_path, {"mode": "search", "steerer": "jev"})

    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=private\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Gemini"):
        validate_provider_settings(tmp_path, {"mode": "search", "steerer": "jev"})


def test_research_requires_planner_key_even_with_jev_steering(tmp_path, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=private\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Gemini"):
        validate_provider_settings(tmp_path, {"mode": "research", "steerer": "jev"})
