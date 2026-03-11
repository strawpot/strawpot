"""File-based ask_user bridge for GUI-mediated interactive sessions.

When ``STRAWPOT_ASK_USER_BRIDGE=file`` the Session swaps the default
auto-responder for a handler that writes questions to disk and polls
for a response file written by the GUI.
"""

import json
import logging
import os
import threading
import time
import uuid

from strawpot.session import AskUserRequest, AskUserResponse

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.5
DEFAULT_TIMEOUT_S = 300  # 5 minutes

# Lock shared across all handler calls within a process for
# thread-safe appends to chat_messages.jsonl.
_chat_lock = threading.Lock()


def _append_chat_message(
    session_dir: str, role: str, text: str, msg_id: str, timestamp: float
) -> None:
    """Append a chat message to chat_messages.jsonl, thread-safe."""
    path = os.path.join(session_dir, "chat_messages.jsonl")
    entry = json.dumps(
        {"id": msg_id, "role": role, "text": text, "timestamp": timestamp}
    )
    with _chat_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")


def make_file_bridge_handler(
    session_dir: str,
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
):
    """Return an ask_user handler that bridges via filesystem.

    The returned callable:
    1. Writes ``ask_user_pending_<request_id>.json`` with the question
    2. Persists the agent question to ``chat_messages.jsonl``
    3. Polls for ``ask_user_response_<request_id>.json``
    4. Reads the response, persists it, cleans up both files
    5. Returns :class:`AskUserResponse`
    6. On timeout falls back to *default_value* or a generic message
    """

    def handler(req: AskUserRequest) -> AskUserResponse:
        request_id = uuid.uuid4().hex[:12]
        pending_path = os.path.join(
            session_dir, f"ask_user_pending_{request_id}.json"
        )
        response_path = os.path.join(
            session_dir, f"ask_user_response_{request_id}.json"
        )

        ts = time.time()
        pending_data = {
            "request_id": request_id,
            "question": req.question,
            "choices": req.choices,
            "default_value": req.default_value,
            "why": req.why,
            "response_format": req.response_format,
            "timestamp": ts,
        }

        # Atomic write: tmp → rename
        tmp_path = pending_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(pending_data, f, indent=2)
        os.replace(tmp_path, pending_path)

        # Persist agent question to chat history
        _append_chat_message(session_dir, "agent", req.question, request_id, ts)

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

                # Persist user answer to chat history
                resp_text = resp_data.get("text", "")
                _append_chat_message(
                    session_dir, "user", resp_text,
                    f"user-{request_id}", time.time(),
                )

                _safe_remove(pending_path)
                _safe_remove(response_path)

                logger.info("ask_user bridge: got response for %s", request_id)
                return AskUserResponse(
                    text=resp_text,
                    json=resp_data.get("json", ""),
                )

            time.sleep(POLL_INTERVAL_S)

        # Timeout — clean up and fall back
        _safe_remove(pending_path)
        fallback_text = req.default_value or "Proceed with your best judgment."
        _append_chat_message(
            session_dir, "user", f"[timeout] {fallback_text}",
            f"user-{request_id}", time.time(),
        )
        logger.warning("ask_user bridge: timeout for %s, using default", request_id)
        return AskUserResponse(text=fallback_text)

    return handler


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
