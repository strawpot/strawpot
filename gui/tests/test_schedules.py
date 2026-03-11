"""Tests for scheduled tasks CRUD endpoints."""

import pytest


@pytest.fixture
def project_id(client, tmp_path):
    """Create a project and return its id."""
    resp = client.post(
        "/api/projects",
        json={"display_name": "test-proj", "working_dir": str(tmp_path)},
    )
    return resp.json()["id"]


class TestCreateSchedule:
    def test_create(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "nightly",
                "project_id": project_id,
                "task": "run tests",
                "cron_expr": "0 0 * * *",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "nightly"
        assert data["task"] == "run tests"
        assert data["cron_expr"] == "0 0 * * *"
        assert data["enabled"] is True  # DB default is enabled
        assert data["skip_if_running"] is True
        assert data["next_run_at"] is not None

    def test_create_with_optional_fields(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "daily",
                "project_id": project_id,
                "task": "deploy",
                "cron_expr": "30 8 * * *",
                "role": "team-lead",
                "system_prompt": "Be thorough",
                "skip_if_running": False,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["role"] == "team-lead"
        assert data["system_prompt"] == "Be thorough"
        assert data["skip_if_running"] is False

    def test_invalid_cron_returns_422(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "bad",
                "project_id": project_id,
                "task": "x",
                "cron_expr": "not-a-cron",
            },
        )
        assert resp.status_code == 422

    def test_empty_name_returns_422(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "  ",
                "project_id": project_id,
                "task": "x",
                "cron_expr": "0 0 * * *",
            },
        )
        assert resp.status_code == 422

    def test_empty_task_returns_422(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "ok",
                "project_id": project_id,
                "task": "  ",
                "cron_expr": "0 0 * * *",
            },
        )
        assert resp.status_code == 422

    def test_nonexistent_project_returns_404(self, client):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "x",
                "project_id": 999,
                "task": "x",
                "cron_expr": "0 0 * * *",
            },
        )
        assert resp.status_code == 404

    def test_duplicate_name_returns_409(self, client, project_id):
        body = {
            "name": "unique",
            "project_id": project_id,
            "task": "x",
            "cron_expr": "0 0 * * *",
        }
        client.post("/api/schedules", json=body)
        resp = client.post("/api/schedules", json=body)
        assert resp.status_code == 409


class TestGetSchedule:
    def test_get(self, client, project_id):
        create = client.post(
            "/api/schedules",
            json={
                "name": "s1",
                "project_id": project_id,
                "task": "t",
                "cron_expr": "0 0 * * *",
            },
        )
        sid = create.json()["id"]
        resp = client.get(f"/api/schedules/{sid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "s1"

    def test_not_found(self, client):
        resp = client.get("/api/schedules/999")
        assert resp.status_code == 404


class TestListSchedules:
    def test_empty(self, client):
        resp = client.get("/api/schedules")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_all(self, client, project_id):
        for name in ["a", "b", "c"]:
            client.post(
                "/api/schedules",
                json={
                    "name": name,
                    "project_id": project_id,
                    "task": "t",
                    "cron_expr": "0 0 * * *",
                },
            )
        resp = client.get("/api/schedules")
        assert len(resp.json()) == 3

    def test_includes_project_name(self, client, project_id):
        client.post(
            "/api/schedules",
            json={
                "name": "s",
                "project_id": project_id,
                "task": "t",
                "cron_expr": "0 0 * * *",
            },
        )
        resp = client.get("/api/schedules")
        assert resp.json()[0]["project_name"] == "test-proj"


class TestUpdateSchedule:
    def _create(self, client, project_id, name="orig"):
        resp = client.post(
            "/api/schedules",
            json={
                "name": name,
                "project_id": project_id,
                "task": "original task",
                "cron_expr": "0 0 * * *",
            },
        )
        return resp.json()["id"]

    def test_update_name(self, client, project_id):
        sid = self._create(client, project_id)
        resp = client.put(f"/api/schedules/{sid}", json={"name": "renamed"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "renamed"

    def test_update_task(self, client, project_id):
        sid = self._create(client, project_id)
        resp = client.put(f"/api/schedules/{sid}", json={"task": "new task"})
        assert resp.status_code == 200
        assert resp.json()["task"] == "new task"

    def test_update_cron(self, client, project_id):
        sid = self._create(client, project_id)
        resp = client.put(
            f"/api/schedules/{sid}", json={"cron_expr": "*/5 * * * *"}
        )
        assert resp.status_code == 200
        assert resp.json()["cron_expr"] == "*/5 * * * *"

    def test_empty_body_returns_422(self, client, project_id):
        sid = self._create(client, project_id)
        resp = client.put(f"/api/schedules/{sid}", json={})
        assert resp.status_code == 422

    def test_not_found(self, client):
        resp = client.put("/api/schedules/999", json={"name": "x"})
        assert resp.status_code == 404

    def test_duplicate_name_returns_409(self, client, project_id):
        self._create(client, project_id, name="first")
        sid2 = self._create(client, project_id, name="second")
        resp = client.put(f"/api/schedules/{sid2}", json={"name": "first"})
        assert resp.status_code == 409

    def test_invalid_cron_returns_422(self, client, project_id):
        sid = self._create(client, project_id)
        resp = client.put(
            f"/api/schedules/{sid}", json={"cron_expr": "bad-cron"}
        )
        assert resp.status_code == 422


class TestDeleteSchedule:
    def test_delete(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "del",
                "project_id": project_id,
                "task": "t",
                "cron_expr": "0 0 * * *",
            },
        )
        sid = resp.json()["id"]
        resp = client.delete(f"/api/schedules/{sid}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert client.get(f"/api/schedules/{sid}").status_code == 404

    def test_not_found(self, client):
        resp = client.delete("/api/schedules/999")
        assert resp.status_code == 404


class TestEnableDisable:
    def _create(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "toggle",
                "project_id": project_id,
                "task": "t",
                "cron_expr": "0 0 * * *",
            },
        )
        return resp.json()["id"]

    def test_enable(self, client, project_id):
        sid = self._create(client, project_id)
        resp = client.post(f"/api/schedules/{sid}/enable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["next_run_at"] is not None

    def test_disable(self, client, project_id):
        sid = self._create(client, project_id)
        client.post(f"/api/schedules/{sid}/enable")
        resp = client.post(f"/api/schedules/{sid}/disable")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["next_run_at"] is None

    def test_enable_not_found(self, client):
        assert client.post("/api/schedules/999/enable").status_code == 404

    def test_disable_not_found(self, client):
        assert client.post("/api/schedules/999/disable").status_code == 404


class TestScheduleHistory:
    def test_empty_history(self, client, project_id):
        resp = client.post(
            "/api/schedules",
            json={
                "name": "h",
                "project_id": project_id,
                "task": "t",
                "cron_expr": "0 0 * * *",
            },
        )
        sid = resp.json()["id"]
        resp = client.get(f"/api/schedules/{sid}/history")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_not_found(self, client):
        assert client.get("/api/schedules/999/history").status_code == 404
