"""Tests for file-based ask_user bridge."""

import glob
import json
import os
import threading
import time

from strawpot.ask_user_bridge import make_file_bridge_handler
from strawpot.session import AskUserRequest


def _make_request(**overrides):
    defaults = {
        "question": "What is your name?",
        "choices": [],
        "default_value": "",
        "why": "Need to greet you",
        "response_format": "text",
    }
    defaults.update(overrides)
    return AskUserRequest(**defaults)


def _find_pending(tmp_path):
    """Find the ask_user_pending_*.json file and return (path, data)."""
    pattern = str(tmp_path / "ask_user_pending_*.json")
    files = glob.glob(pattern)
    assert len(files) == 1, f"Expected 1 pending file, found {len(files)}"
    path = files[0]
    data = json.loads(open(path, encoding="utf-8").read())
    return path, data


class TestFileBridgeHandler:
    def test_writes_pending_file(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request()

        # Run handler in background (it will timeout)
        t = threading.Thread(target=handler, args=(req,))
        t.start()
        time.sleep(0.3)

        path, data = _find_pending(tmp_path)
        assert data["question"] == "What is your name?"
        assert data["why"] == "Need to greet you"
        assert "request_id" in data
        # Filename should contain request_id
        assert data["request_id"] in os.path.basename(path)

        t.join(timeout=5)

    def test_response_returned(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=10)
        req = _make_request()

        def write_response():
            time.sleep(0.3)
            _, data = _find_pending(tmp_path)
            req_id = data["request_id"]
            resp = {"request_id": req_id, "text": "Alice"}
            resp_path = tmp_path / f"ask_user_response_{req_id}.json"
            resp_path.write_text(json.dumps(resp))

        t = threading.Thread(target=write_response)
        t.start()

        result = handler(req)
        t.join()

        assert result.text == "Alice"
        # Both files should be cleaned up
        assert len(glob.glob(str(tmp_path / "ask_user_pending_*.json"))) == 0
        assert len(glob.glob(str(tmp_path / "ask_user_response_*.json"))) == 0

    def test_timeout_with_default_value(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request(default_value="Bob")

        result = handler(req)
        assert result.text == "Bob"
        # Pending file should be cleaned up
        assert len(glob.glob(str(tmp_path / "ask_user_pending_*.json"))) == 0

    def test_timeout_without_default(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request()

        result = handler(req)
        assert result.text == "Proceed with your best judgment."

    def test_choices_passed_through(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request(choices=["A", "B", "C"])

        # Let it timeout — just verify the pending file has choices
        def check_pending():
            time.sleep(0.3)
            _, data = _find_pending(tmp_path)
            assert data["choices"] == ["A", "B", "C"]

        t = threading.Thread(target=check_pending)
        t.start()

        handler(req)
        t.join()

    def test_chat_messages_persisted(self, tmp_path):
        """Agent question and user answer are persisted to chat_messages.jsonl."""
        handler = make_file_bridge_handler(str(tmp_path), timeout=10)
        req = _make_request(question="Pick a color")

        def write_response():
            time.sleep(0.3)
            _, data = _find_pending(tmp_path)
            req_id = data["request_id"]
            resp = {"request_id": req_id, "text": "Blue"}
            resp_path = tmp_path / f"ask_user_response_{req_id}.json"
            resp_path.write_text(json.dumps(resp))

        t = threading.Thread(target=write_response)
        t.start()

        result = handler(req)
        t.join()

        assert result.text == "Blue"

        # Verify chat_messages.jsonl has both entries
        chat_path = tmp_path / "chat_messages.jsonl"
        assert chat_path.is_file()
        messages = [
            json.loads(line)
            for line in chat_path.read_text().strip().split("\n")
        ]
        assert len(messages) == 2
        assert messages[0]["role"] == "agent"
        assert messages[0]["text"] == "Pick a color"
        assert messages[1]["role"] == "user"
        assert messages[1]["text"] == "Blue"

    def test_timeout_persists_fallback(self, tmp_path):
        """Timeout fallback is persisted to chat_messages.jsonl."""
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request(default_value="skip")

        handler(req)

        chat_path = tmp_path / "chat_messages.jsonl"
        assert chat_path.is_file()
        messages = [
            json.loads(line)
            for line in chat_path.read_text().strip().split("\n")
        ]
        assert len(messages) == 2
        assert messages[0]["role"] == "agent"
        assert messages[1]["role"] == "user"
        assert "[timeout]" in messages[1]["text"]
