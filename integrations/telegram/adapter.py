"""Telegram adapter for StrawPot — relays messages to/from imu."""

import asyncio
import json
import logging
import os
import signal
import sqlite3
import sys
from pathlib import Path

import httpx
import websockets
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("strawpot.telegram")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_URL = os.environ.get("STRAWPOT_API_URL", "http://127.0.0.1:52532")
BOT_TOKEN = os.environ.get("STRAWPOT_BOT_TOKEN", "")
# Max chars per Telegram message (leave room for formatting)
TG_MAX_LEN = 4000
# How often to poll for session status if WebSocket fails (seconds)
POLL_INTERVAL = 3

if not BOT_TOKEN:
    logger.error("STRAWPOT_BOT_TOKEN is not set")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Local database: chat_id → conversation_id mapping
# ---------------------------------------------------------------------------

_DB_PATH = Path(__file__).parent / ".adapter.db"


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_conversations (
            chat_id   TEXT PRIMARY KEY,
            conv_id   INTEGER NOT NULL
        )
        """
    )
    conn.commit()
    return conn


db = _init_db()


def get_conv_id(chat_id: str) -> int | None:
    row = db.execute(
        "SELECT conv_id FROM chat_conversations WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    return row[0] if row else None


def set_conv_id(chat_id: str, conv_id: int) -> None:
    db.execute(
        "INSERT OR REPLACE INTO chat_conversations (chat_id, conv_id) VALUES (?, ?)",
        (chat_id, conv_id),
    )
    db.commit()


# ---------------------------------------------------------------------------
# StrawPot API helpers
# ---------------------------------------------------------------------------


async def create_conversation(client: httpx.AsyncClient) -> int:
    """Create a new imu conversation and return its ID."""
    resp = await client.post(f"{API_URL}/api/imu/conversations")
    resp.raise_for_status()
    return resp.json()["id"]


async def get_or_create_conversation(
    client: httpx.AsyncClient, chat_id: str
) -> int:
    """Get existing conversation for this chat, or create a new one."""
    conv_id = get_conv_id(chat_id)
    if conv_id is not None:
        return conv_id
    conv_id = await create_conversation(client)
    set_conv_id(chat_id, conv_id)
    logger.info("Created conversation %d for chat %s", conv_id, chat_id)
    return conv_id


async def submit_task(
    client: httpx.AsyncClient, conv_id: int, text: str
) -> dict:
    """Submit a task to a conversation. Returns the response dict."""
    resp = await client.post(
        f"{API_URL}/api/conversations/{conv_id}/tasks",
        json={"task": text},
    )
    resp.raise_for_status()
    return resp.json()


async def get_session_summary(
    client: httpx.AsyncClient, conv_id: int, run_id: str
) -> str:
    """Fetch the session summary from the conversation."""
    resp = await client.get(f"{API_URL}/api/conversations/{conv_id}")
    resp.raise_for_status()
    for session in resp.json().get("sessions", []):
        if session["run_id"] == run_id:
            return session.get("summary") or f"Session {session['status']}."
    return "Session completed."


# ---------------------------------------------------------------------------
# Session monitoring
# ---------------------------------------------------------------------------


async def wait_for_session_ws(run_id: str) -> None:
    """Wait for a session to complete via WebSocket."""
    ws_url = API_URL.replace("http://", "ws://").replace("https://", "wss://")
    uri = f"{ws_url}/ws/sessions/{run_id}"
    try:
        async with websockets.connect(uri) as ws:
            # Send init to start receiving events
            await ws.send(json.dumps({"type": "init", "trace_offset": 0}))
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "stream_complete":
                    return
                if msg.get("type") == "error":
                    logger.warning("WS error: %s", msg.get("message"))
                    return
    except Exception as exc:
        logger.warning("WebSocket monitoring failed: %s — falling back to polling", exc)
        await wait_for_session_poll(run_id)


async def wait_for_session_poll(run_id: str) -> None:
    """Fallback: poll session status until terminal."""
    terminal = {"completed", "failed", "stopped"}
    async with httpx.AsyncClient() as client:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                resp = await client.get(f"{API_URL}/api/sessions/{run_id}")
                resp.raise_for_status()
                if resp.json().get("status") in terminal:
                    return
            except Exception as exc:
                logger.warning("Poll error: %s", exc)


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


def chunk_message(text: str) -> list[str]:
    """Split text into chunks that fit Telegram's message limit."""
    if len(text) <= TG_MAX_LEN:
        return [text]
    chunks = []
    while text:
        if len(text) <= TG_MAX_LEN:
            chunks.append(text)
            break
        # Try to break at a newline
        cut = text.rfind("\n", 0, TG_MAX_LEN)
        if cut < TG_MAX_LEN // 2:
            cut = TG_MAX_LEN
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


# ---------------------------------------------------------------------------
# Telegram handlers
# ---------------------------------------------------------------------------


async def cmd_start(update: Update, context) -> None:
    """Handle /start — welcome message."""
    await update.message.reply_text(
        "Hi! I'm your StrawPot assistant.\n\n"
        "Send me a message and I'll route it through imu.\n"
        "Use /new to start a fresh conversation."
    )


async def cmd_new(update: Update, context) -> None:
    """Handle /new — start a fresh conversation."""
    chat_id = str(update.effective_chat.id)
    async with httpx.AsyncClient() as client:
        conv_id = await create_conversation(client)
    set_conv_id(chat_id, conv_id)
    logger.info("New conversation %d for chat %s", conv_id, chat_id)
    await update.message.reply_text("New conversation started.")


async def handle_message(update: Update, context) -> None:
    """Handle incoming text message — submit as task to imu."""
    chat_id = str(update.effective_chat.id)
    text = update.message.text
    if not text:
        return

    logger.info("Message from chat %s: %s", chat_id, text[:100])

    # Show typing indicator
    await update.effective_chat.send_action(ChatAction.TYPING)

    async with httpx.AsyncClient(timeout=30) as client:
        conv_id = await get_or_create_conversation(client, chat_id)

        try:
            result = await submit_task(client, conv_id, text)
        except httpx.HTTPStatusError as exc:
            logger.error("Task submission failed: %s", exc)
            await update.message.reply_text(
                "Failed to submit task. Is StrawPot GUI running?"
            )
            return

        if result.get("queued"):
            await update.message.reply_text(
                "Queued — will run after the current session finishes."
            )
            return

        run_id = result.get("run_id")
        if not run_id:
            await update.message.reply_text("Task submitted.")
            return

        # Acknowledge
        ack = await update.message.reply_text("On it...")

    # Wait for session to complete
    await wait_for_session_ws(run_id)

    # Fetch and send the summary
    async with httpx.AsyncClient(timeout=30) as client:
        summary = await get_session_summary(client, conv_id, run_id)

    # Delete the "On it..." message
    try:
        await ack.delete()
    except Exception:
        pass

    for chunk in chunk_message(summary):
        await update.message.reply_text(chunk)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logger.info("Starting Telegram adapter")
    logger.info("API URL: %s", API_URL)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Graceful shutdown on SIGTERM (sent by StrawPot GUI)
    def handle_sigterm(signum, frame):
        logger.info("Received SIGTERM, shutting down...")
        app.stop_running()

    signal.signal(signal.SIGTERM, handle_sigterm)

    logger.info("Bot is running — polling for updates")
    app.run_polling(drop_pending_updates=True)
    logger.info("Bot stopped")


if __name__ == "__main__":
    main()
