from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import settings_store


def test_shared_pat_used_for_both_providers_when_provider_tokens_missing(monkeypatch):
    monkeypatch.setattr(settings_store, "load_settings", lambda: {})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("GIT_SHARED_PAT", "shared-token-123456")

    assert settings_store.get_github_token() == "shared-token-123456"
    assert settings_store.get_gitlab_token() == "shared-token-123456"


def test_provider_env_tokens_override_shared_pat(monkeypatch):
    monkeypatch.setattr(settings_store, "load_settings", lambda: {})
    monkeypatch.setenv("GIT_SHARED_PAT", "shared-token-123456")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITLAB_TOKEN", "gitlab-token")

    assert settings_store.get_github_token() == "github-token"
    assert settings_store.get_gitlab_token() == "gitlab-token"


def test_persisted_settings_tokens_override_provider_env_and_shared_pat(monkeypatch):
    monkeypatch.setattr(
        settings_store,
        "load_settings",
        lambda: {
            "github": {"token": "persisted-gh"},
            "gitlab": {"token": "persisted-gl"},
        },
    )
    monkeypatch.setenv("GIT_SHARED_PAT", "shared-token-123456")
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITLAB_TOKEN", "gitlab-token")

    assert settings_store.get_github_token() == "persisted-gh"
    assert settings_store.get_gitlab_token() == "persisted-gl"


def test_settings_masking_uses_resolved_shared_pat(monkeypatch):
    monkeypatch.setattr(settings_store, "load_settings", lambda: {})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("GIT_SHARED_PAT", "abcdef123456")

    github_settings = settings_store.get_github_settings()
    gitlab_settings = settings_store.get_gitlab_settings()

    assert github_settings["has_token"] is True
    assert gitlab_settings["has_token"] is True
    assert github_settings["token_masked"] == "********3456"
    assert gitlab_settings["token_masked"] == "********3456"


def test_assist_git_pat_alias_is_supported(monkeypatch):
    monkeypatch.setattr(settings_store, "load_settings", lambda: {})
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GIT_SHARED_PAT", raising=False)
    monkeypatch.setenv("ASSIST_GIT_PAT", "alias-shared-token")

    assert settings_store.get_github_token() == "alias-shared-token"
    assert settings_store.get_gitlab_token() == "alias-shared-token"
