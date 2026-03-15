---
name: telegram
description: Telegram bot adapter for StrawPot conversations
metadata:
  strawpot:
    entry_point: python adapter.py
    auto_start: false
    install:
      macos: pip install -r requirements.txt
      linux: pip install -r requirements.txt
    config:
      bot_token:
        type: secret
        required: true
        description: Telegram bot API token from @BotFather
---

# Telegram Adapter

Connects a Telegram bot to StrawPot via imu. Messages sent to the bot
become tasks in imu conversations; session outputs are replied back in
the chat.

## Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram
2. Copy the bot token
3. Install this integration and its dependencies:
   ```bash
   cp -r integrations/telegram ~/.strawpot/integrations/telegram
   cd ~/.strawpot/integrations/telegram && pip install -r requirements.txt
   ```
4. In the StrawPot GUI, go to **Integrations** → **telegram** → **Configure**
5. Paste the bot token and click Save
6. Click **Start**

> **Future:** `strawhub install integration telegram` will handle step 3
> automatically, including running the `install` command from the manifest.

## How it works

- Each Telegram chat (DM or group) maps to a separate imu conversation
- Messages are submitted as tasks to imu via the StrawPot REST API
- The adapter monitors the session via WebSocket and replies with the
  summary when done
- Use `/new` to start a fresh conversation (clears the chat→conversation
  mapping)
- Use `/start` to see a welcome message

## Conversation mapping

The adapter stores `chat_id → conversation_id` in a local SQLite
database (`.adapter.db` in the integration directory). This is adapter
state only — the StrawPot GUI sees normal imu conversations.

## Group chats

In group chats, the bot responds to:
- Direct replies to the bot's messages
- Messages that mention the bot by name
- All `/new` and `/start` commands

To add the bot to a group, disable "Group Privacy" in BotFather settings
or use the bot in reply-only mode.
