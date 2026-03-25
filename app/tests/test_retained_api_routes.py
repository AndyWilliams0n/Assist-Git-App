from pathlib import Path
import sys

from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import app


def test_required_workspace_git_and_provider_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/api/workspaces" in paths
    assert "/api/workspaces/active-config" in paths
    assert "/api/git/status" in paths
    assert "/api/git/status/stream" in paths
    assert "/api/github/settings" in paths
    assert "/api/github/repos" in paths
    assert "/api/gitlab/settings" in paths
    assert "/api/gitlab/repos" in paths


def test_github_repos_returns_actionable_token_error_without_config(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GIT_SHARED_PAT", raising=False)
    monkeypatch.delenv("ASSIST_GIT_PAT", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/github/repos")

    assert response.status_code == 400
    assert "GITHUB_TOKEN" in response.json()["detail"]
    assert "GIT_SHARED_PAT" in response.json()["detail"]


def test_gitlab_repos_returns_actionable_token_error_without_config(monkeypatch):
    monkeypatch.delenv("GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("GIT_SHARED_PAT", raising=False)
    monkeypatch.delenv("ASSIST_GIT_PAT", raising=False)

    with TestClient(app) as client:
        response = client.get("/api/gitlab/repos")

    assert response.status_code == 400
    assert "GITLAB_TOKEN" in response.json()["detail"]
    assert "GIT_SHARED_PAT" in response.json()["detail"]
