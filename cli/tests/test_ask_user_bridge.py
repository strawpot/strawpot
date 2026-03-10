"""Tests for file-based ask_user bridge."""

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


class TestFileBridgeHandler:
    def test_writes_pending_file(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request()

        # Run handler in background (it will timeout)
        t = threading.Thread(target=handler, args=(req,))
        t.start()
        time.sleep(0.3)

        pending = tmp_path / "ask_user_pending.json"
        assert pending.is_file()
        data = json.loads(pending.read_text())
        assert data["question"] == "What is your name?"
        assert data["why"] == "Need to greet you"
        assert "request_id" in data

        t.join(timeout=5)

    def test_response_returned(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=10)
        req = _make_request()

        def write_response():
            time.sleep(0.3)
            pending = tmp_path / "ask_user_pending.json"
            data = json.loads(pending.read_text())
            resp = {"request_id": data["request_id"], "text": "Alice"}
            (tmp_path / "ask_user_response.json").write_text(json.dumps(resp))

        t = threading.Thread(target=write_response)
        t.start()

        result = handler(req)
        t.join()

        assert result.text == "Alice"
        # Both files should be cleaned up
        assert not (tmp_path / "ask_user_pending.json").exists()
        assert not (tmp_path / "ask_user_response.json").exists()

    def test_timeout_with_default_value(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request(default_value="Bob")

        result = handler(req)
        assert result.text == "Bob"
        # Pending file should be cleaned up
        assert not (tmp_path / "ask_user_pending.json").exists()

    def test_timeout_without_default(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request()

        result = handler(req)
        assert result.text == "Proceed with your best judgment."

    def test_ignores_wrong_request_id(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=2)
        req = _make_request(default_value="fallback")

        def write_bad_then_good():
            time.sleep(0.3)
            # Write response with wrong request_id
            (tmp_path / "ask_user_response.json").write_text(
                json.dumps({"request_id": "wrong", "text": "Bad"})
            )
            time.sleep(0.8)
            # Now write correct one
            pending = tmp_path / "ask_user_pending.json"
            if pending.is_file():
                data = json.loads(pending.read_text())
                (tmp_path / "ask_user_response.json").write_text(
                    json.dumps({"request_id": data["request_id"], "text": "Good"})
                )

        t = threading.Thread(target=write_bad_then_good)
        t.start()

        result = handler(req)
        t.join()

        assert result.text == "Good"

    def test_choices_passed_through(self, tmp_path):
        handler = make_file_bridge_handler(str(tmp_path), timeout=1)
        req = _make_request(choices=["A", "B", "C"])

        # Let it timeout — just verify the pending file has choices
        def check_pending():
            time.sleep(0.3)
            pending = tmp_path / "ask_user_pending.json"
            data = json.loads(pending.read_text())
            assert data["choices"] == ["A", "B", "C"]

        t = threading.Thread(target=check_pending)
        t.start()

        handler(req)
        t.join()
