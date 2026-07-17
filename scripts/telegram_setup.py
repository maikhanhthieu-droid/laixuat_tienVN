#!/usr/bin/env python3
"""Discover Telegram chat IDs after the user has messaged the bot."""
from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from telegram_publish import TelegramClient, TelegramError


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        token = getpass("Telegram bot token (input hidden): ").strip()
    if not token:
        print("Telegram bot token is required.", file=sys.stderr)
        return 2
    try:
        updates = TelegramClient(token).get_updates()
    except TelegramError as exc:
        print(f"Cannot read Telegram updates: {exc}", file=sys.stderr)
        return 1

    chats: dict[str, str] = {}
    for update in updates:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        label = (
            chat.get("title")
            or " ".join(
                part for part in [chat.get("first_name"), chat.get("last_name")] if part
            )
            or chat.get("username")
            or chat.get("type", "chat")
        )
        chats[str(chat_id)] = str(label)

    if not chats:
        print("No chats found. Send /start to the bot, then run this command again.")
        return 0
    print("Discovered chats:")
    for chat_id, label in chats.items():
        print(f"  {chat_id}  {label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
