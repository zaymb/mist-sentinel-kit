#!/usr/bin/env python3
"""Send a multiline sentinel event through Telegram with a collapsed body."""

from __future__ import annotations

import argparse
import datetime
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# Telegram Bot API sendMessage: 1–4096 characters after entity parsing.
# https://core.telegram.org/bots/api#sendmessage
TELEGRAM_TEXT_LIMIT = 4096


def utf16_length(text: str) -> int:
    """Telegram entity offsets count UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def truncate_utf16(text: str, limit: int) -> str:
    if utf16_length(text) <= limit:
        return text
    if limit <= 1:
        return "…" if limit == 1 else ""
    kept = []
    used = 0
    for character in text:
        width = 2 if ord(character) > 0xFFFF else 1
        if used + width > limit - 1:
            break
        kept.append(character)
        used += width
    return "".join(kept) + "…"


def numbered_body(body: str) -> str:
    chunks = [chunk.strip() for chunk in body.split("\n——\n") if chunk.strip()]
    return "\n\n".join(f"{index}. {chunk}" for index, chunk in enumerate(chunks, start=1))


def render_html(event_text: str) -> str:
    summary, separator, body = event_text.partition("\n")
    summary = truncate_utf16(f"🔔 {summary}", TELEGRAM_TEXT_LIMIT)
    if not separator or not body.strip():
        return html.escape(summary)

    remaining = TELEGRAM_TEXT_LIMIT - utf16_length(summary) - 1
    collapsed = truncate_utf16(numbered_body(body), remaining)
    if not collapsed:
        return html.escape(summary)
    return f"{html.escape(summary)}\n<blockquote expandable>{html.escape(collapsed)}</blockquote>"


def append_line(path, line: str) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line.rstrip("\n") + "\n")


def send_message(token: str, chat_id: str, text: str) -> None:
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": json.dumps({"is_disabled": True}),
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Telegram HTTP {response.status}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event_text")
    parser.add_argument("--event-log")
    parser.add_argument("--error-log")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # events.log remains one summary per line so file monitors do not mistake
    # a multiline comment body for several independent events.
    append_line(args.event_log, args.event_text.partition("\n")[0])
    rendered = render_html(args.event_text)
    if args.dry_run:
        print(rendered)
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        append_line(args.error_log, "telegram notifier missing token or chat id")
        return 2

    try:
        send_message(token, chat_id, rendered)
    except urllib.error.HTTPError as error:
        append_line(args.error_log, f"{datetime.datetime.now():%H:%M} telegram HTTP {error.code}")
        return 1
    except (urllib.error.URLError, OSError, RuntimeError) as error:
        append_line(
            args.error_log,
            f"{datetime.datetime.now():%H:%M} telegram send failed ({type(error).__name__})",
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
