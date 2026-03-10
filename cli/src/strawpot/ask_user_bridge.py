"""File-based ask_user bridge for GUI-mediated interactive sessions.

When ``STRAWPOT_ASK_USER_BRIDGE=file`` the Session swaps the default
auto-responder for a handler that writes questions to disk and polls
for a response file written by the GUI.
"""

import json
import logging
import os
import time
import uuid

from strawpot.session import AskUserRequest, AskUserResponse

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.5
DEFAULT_TIMEOUT_S = 300  # 5 minutes


def make_file_bridge_handler(
    session_dir: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
):
    """Return an ask_user handler that bridges via filesystem.

    The returned callable:
    1. Writes ``ask_user_pending.json`` with the question
    2. Polls for ``ask_user_response.json``
    3. Reads the response, cleans up both files
    4. Returns :class:`AskUserResponse`
    5. On timeout falls back to *default_value* or a generic message
    """

    def handler(req: AskUserRequest) -> AskUserResponse:
        request_id = uuid.uuid4().hex[:12]
        pending_path = os.path.join(session_dir, "ask_user_pending.json")
        response_path = os.path.join(session_dir, "ask_user_response.json")

        pending_data = {
            "request_id": request_id,
            "question": req.question,
            "choices": req.choices,
            "default_value": req.default_value,
            "why": req.why,
            "response_format": req.response_format,
            "timestamp": time.time(),
        }

        # Atomic write: tmp → rename
        tmp_path = pending_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2)
        os.replace(tmp_path, pending_path)

        logger.info("ask_user bridge: wrote pending request %s", request_id)

        # Poll for response
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if os.path.isfile(response_path):
                try:
                    with open(response_path, encoding="utf-8") as f:
                        resp_data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    time.sleep(POLL_INTERVAL_S)
                    continue

                if resp_data.get("request_id") != request_id:
                    time.sleep(POLL_INTERVAL_S)
                    continue

                _safe_remove(pending_path)
                _safe_remove(response_path)

                logger.info("ask_user bridge: got response for %s", request_id)
                return AskUserResponse(
                    text=resp_data.get("text", ""),
                    json=resp_data.get("json", ""),
                )

            time.sleep(POLL_INTERVAL_S)

        # Timeout — clean up and fall back
        _safe_remove(pending_path)
        logger.warning("ask_user bridge: timeout for %s, using default", request_id)
        if req.default_value:
            return AskUserResponse(text=req.default_value)
        return AskUserResponse(text="Proceed with your best judgment.")

    return handler


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
