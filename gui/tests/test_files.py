"""Tests for project file upload, listing, and deletion endpoints."""

import pytest


@pytest.fixture
def project(client, tmp_path):
    """Create a project with tmp_path as working_dir and return (id, tmp_path)."""
    resp = client.post(
        "/api/projects",
        json={"display_name": "files-proj", "working_dir": str(tmp_path)},
    )
    return resp.json()["id"], tmp_path


class TestListFiles:
    def test_empty_when_no_files_dir(self, client, project):
        pid, _ = project
        resp = client.get(f"/api/projects/{pid}/files")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_uploaded_files(self, client, project):
        pid, tmp_path = project
        files_dir = tmp_path / ".strawpot" / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "a.txt").write_text("hello")
        (files_dir / "b.txt").write_text("world")

        resp = client.get(f"/api/projects/{pid}/files")
        assert resp.status_code == 200
        names = [f["name"] for f in resp.json()]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_lists_nested_files(self, client, project):
        pid, tmp_path = project
        files_dir = tmp_path / ".strawpot" / "files"
        sub = files_dir / "sub"
        sub.mkdir(parents=True)
        (sub / "nested.txt").write_text("deep")

        resp = client.get(f"/api/projects/{pid}/files")
        entries = resp.json()
        assert len(entries) == 1
        assert entries[0]["name"] == "nested.txt"
        assert "sub" in entries[0]["path"]

    def test_nonexistent_project_returns_404(self, client):
        resp = client.get("/api/projects/999/files")
        assert resp.status_code == 404


class TestUploadFiles:
    def test_upload_single_file(self, client, project):
        pid, tmp_path = project
        resp = client.post(
            f"/api/projects/{pid}/files",
            files=[("files", ("test.txt", b"content", "text/plain"))],
        )
        assert resp.status_code == 201
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "test.txt"
        assert (tmp_path / ".strawpot" / "files" / "test.txt").is_file()

    def test_upload_multiple_files(self, client, project):
        pid, _ = project
        resp = client.post(
            f"/api/projects/{pid}/files",
            files=[
                ("files", ("a.txt", b"aaa", "text/plain")),
                ("files", ("b.txt", b"bbb", "text/plain")),
            ],
        )
        assert resp.status_code == 201
        assert len(resp.json()) == 2

    def test_path_traversal_rejected(self, client, project):
        pid, _ = project
        resp = client.post(
            f"/api/projects/{pid}/files",
            files=[("files", ("../escape.txt", b"bad", "text/plain"))],
        )
        assert resp.status_code == 400

    def test_absolute_path_rejected(self, client, project):
        pid, _ = project
        resp = client.post(
            f"/api/projects/{pid}/files",
            files=[("files", ("/etc/passwd", b"bad", "text/plain"))],
        )
        assert resp.status_code == 400

    def test_nonexistent_project_returns_404(self, client):
        resp = client.post(
            "/api/projects/999/files",
            files=[("files", ("test.txt", b"x", "text/plain"))],
        )
        assert resp.status_code == 404


class TestDeleteFile:
    def test_delete_file(self, client, project):
        pid, tmp_path = project
        files_dir = tmp_path / ".strawpot" / "files"
        files_dir.mkdir(parents=True)
        (files_dir / "doomed.txt").write_text("bye")

        resp = client.delete(f"/api/projects/{pid}/files/doomed.txt")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert not (files_dir / "doomed.txt").exists()

    def test_delete_cleans_empty_parents(self, client, project):
        pid, tmp_path = project
        files_dir = tmp_path / ".strawpot" / "files"
        sub = files_dir / "sub"
        sub.mkdir(parents=True)
        (sub / "file.txt").write_text("x")

        client.delete(f"/api/projects/{pid}/files/sub/file.txt")
        assert not sub.exists()

    def test_file_not_found_returns_404(self, client, project):
        pid, tmp_path = project
        files_dir = tmp_path / ".strawpot" / "files"
        files_dir.mkdir(parents=True)

        resp = client.delete(f"/api/projects/{pid}/files/nope.txt")
        assert resp.status_code == 404

    def test_path_traversal_rejected(self, client, project):
        pid, tmp_path = project
        files_dir = tmp_path / ".strawpot" / "files"
        files_dir.mkdir(parents=True)
        # Create a file outside files_dir to attempt to reach
        (tmp_path / ".strawpot" / "secret.txt").write_text("secret")
        resp = client.delete(f"/api/projects/{pid}/files/sub/../../../secret.txt")
        # FastAPI or the handler rejects traversal (400, 404, or 422)
        assert resp.status_code >= 400

    def test_nonexistent_project_returns_404(self, client):
        resp = client.delete("/api/projects/999/files/test.txt")
        assert resp.status_code == 404
