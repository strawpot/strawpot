"""Tests for filesystem browsing endpoints."""

import subprocess


class TestBrowse:
    def test_browse_default_home(self, client):
        resp = client.get("/api/fs/browse")
        assert resp.status_code == 200
        data = resp.json()
        assert "path" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)

    def test_browse_specific_path(self, client, tmp_path):
        (tmp_path / "alpha").mkdir()
        (tmp_path / "beta").mkdir()
        resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["path"] == str(tmp_path)
        names = [e["name"] for e in data["entries"]]
        assert "alpha" in names
        assert "beta" in names

    def test_browse_excludes_hidden_dirs(self, client, tmp_path):
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "visible").mkdir()
        resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
        names = [e["name"] for e in resp.json()["entries"]]
        assert "visible" in names
        assert ".hidden" not in names

    def test_browse_excludes_files(self, client, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "file.txt").write_text("hello")
        resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
        names = [e["name"] for e in resp.json()["entries"]]
        assert "subdir" in names
        assert "file.txt" not in names

    def test_browse_returns_parent(self, client, tmp_path):
        child = tmp_path / "child"
        child.mkdir()
        resp = client.get("/api/fs/browse", params={"path": str(child)})
        assert resp.json()["parent"] == str(tmp_path)

    def test_browse_invalid_path_returns_400(self, client, tmp_path):
        resp = client.get(
            "/api/fs/browse", params={"path": str(tmp_path / "nonexistent")}
        )
        assert resp.status_code == 400

    def test_browse_sorted_case_insensitive(self, client, tmp_path):
        (tmp_path / "Zebra").mkdir()
        (tmp_path / "apple").mkdir()
        (tmp_path / "Banana").mkdir()
        resp = client.get("/api/fs/browse", params={"path": str(tmp_path)})
        names = [e["name"] for e in resp.json()["entries"]]
        assert names == ["apple", "Banana", "Zebra"]


class TestMkdir:
    def test_create_directory(self, client, tmp_path):
        resp = client.post(
            "/api/fs/mkdir", json={"path": str(tmp_path), "name": "new-folder"}
        )
        assert resp.status_code == 200
        assert (tmp_path / "new-folder").is_dir()

    def test_invalid_parent_returns_400(self, client, tmp_path):
        resp = client.post(
            "/api/fs/mkdir",
            json={"path": str(tmp_path / "nonexistent"), "name": "x"},
        )
        assert resp.status_code == 400

    def test_empty_name_returns_400(self, client, tmp_path):
        resp = client.post(
            "/api/fs/mkdir", json={"path": str(tmp_path), "name": "  "}
        )
        assert resp.status_code == 400

    def test_slash_in_name_returns_400(self, client, tmp_path):
        resp = client.post(
            "/api/fs/mkdir", json={"path": str(tmp_path), "name": "a/b"}
        )
        assert resp.status_code == 400

    def test_dotfile_name_returns_400(self, client, tmp_path):
        resp = client.post(
            "/api/fs/mkdir", json={"path": str(tmp_path), "name": ".hidden"}
        )
        assert resp.status_code == 400

    def test_already_exists_returns_409(self, client, tmp_path):
        (tmp_path / "existing").mkdir()
        resp = client.post(
            "/api/fs/mkdir", json={"path": str(tmp_path), "name": "existing"}
        )
        assert resp.status_code == 409


class TestGitCheck:
    def test_git_repo_returns_true(self, client, tmp_path):
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        resp = client.get("/api/fs/git-check", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["is_git"] is True

    def test_non_git_returns_false(self, client, tmp_path):
        resp = client.get("/api/fs/git-check", params={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["is_git"] is False

    def test_invalid_path_returns_400(self, client, tmp_path):
        resp = client.get(
            "/api/fs/git-check", params={"path": str(tmp_path / "nope")}
        )
        assert resp.status_code == 400


class TestGitInit:
    def test_init_new_repo(self, client, tmp_path):
        resp = client.post("/api/fs/git-init", json={"path": str(tmp_path)})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert (tmp_path / ".git").is_dir()

    def test_invalid_path_returns_400(self, client, tmp_path):
        resp = client.post(
            "/api/fs/git-init", json={"path": str(tmp_path / "nope")}
        )
        assert resp.status_code == 400
