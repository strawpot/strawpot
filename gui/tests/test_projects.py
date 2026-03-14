"""Tests for project CRUD endpoints."""


class TestCreateProject:
    def test_create_project(self, client, tmp_path):
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        resp = client.post("/api/projects", json={
            "display_name": "My Project",
            "working_dir": str(project_dir),
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["display_name"] == "My Project"
        assert data["dir_exists"] is True
        assert "id" in data
        assert "created_at" in data

    def test_resolves_path(self, client, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        # Pass a path with ".." — should be resolved
        unresolved = str(tmp_path / "sub" / ".." / "sub")
        resp = client.post("/api/projects", json={
            "display_name": "Test",
            "working_dir": unresolved,
        })
        assert resp.status_code == 201
        assert ".." not in resp.json()["working_dir"]

    def test_duplicate_working_dir_returns_409(self, client, tmp_path):
        project_dir = tmp_path / "dup"
        project_dir.mkdir()
        client.post("/api/projects", json={
            "display_name": "First",
            "working_dir": str(project_dir),
        })
        resp = client.post("/api/projects", json={
            "display_name": "Second",
            "working_dir": str(project_dir),
        })
        assert resp.status_code == 409


class TestListProjects:
    def test_empty_list(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_created_projects(self, client, tmp_path):
        d1 = tmp_path / "p1"
        d1.mkdir()
        d2 = tmp_path / "p2"
        d2.mkdir()
        client.post("/api/projects", json={"display_name": "P1", "working_dir": str(d1)})
        client.post("/api/projects", json={"display_name": "P2", "working_dir": str(d2)})

        resp = client.get("/api/projects")
        projects = resp.json()
        assert len(projects) == 2
        assert projects[0]["display_name"] == "P1"
        assert projects[1]["display_name"] == "P2"

    def test_stale_detection(self, client, tmp_path):
        resp = client.post("/api/projects", json={
            "display_name": "Ghost",
            "working_dir": str(tmp_path / "nonexistent"),
        })
        assert resp.status_code == 201

        resp = client.get("/api/projects")
        projects = resp.json()
        assert len(projects) == 1
        assert projects[0]["dir_exists"] is False


class TestGetProject:
    def test_get_existing(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        create_resp = client.post("/api/projects", json={
            "display_name": "Test",
            "working_dir": str(d),
        })
        pid = create_resp.json()["id"]

        resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "Test"
        assert resp.json()["dir_exists"] is True

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/projects/999")
        assert resp.status_code == 404


class TestUpdateProject:
    def test_update_display_name(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        create_resp = client.post("/api/projects", json={
            "display_name": "Old Name",
            "working_dir": str(d),
        })
        pid = create_resp.json()["id"]

        resp = client.patch(f"/api/projects/{pid}", json={
            "display_name": "New Name",
        })
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "New Name"

    def test_update_missing_returns_404(self, client):
        resp = client.patch("/api/projects/999", json={"display_name": "X"})
        assert resp.status_code == 404


class TestDeleteProject:
    def test_delete_project(self, client, tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        create_resp = client.post("/api/projects", json={
            "display_name": "Doomed",
            "working_dir": str(d),
        })
        pid = create_resp.json()["id"]

        resp = client.delete(f"/api/projects/{pid}")
        assert resp.status_code == 200

        # Verify gone
        resp = client.get(f"/api/projects/{pid}")
        assert resp.status_code == 404

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/projects/999")
        assert resp.status_code == 404

    def test_delete_imu_project_returns_403(self, client):
        """Bot Imu virtual project (id=0) cannot be deleted."""
        resp = client.delete("/api/projects/0")
        assert resp.status_code == 403
        assert "Bot Imu" in resp.json()["detail"]
