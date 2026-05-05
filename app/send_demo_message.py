"""
Send a demo text message through Kapso so it shows up in WhatsApp.

Run from repo root so `.env` is found (`get_settings()`).

Usage::

  python -m app.send_demo_message --to +15551234567

Optional::

  python -m app.send_demo_message --to +15551234567 --text "Hackathon ping"
"""

from __future__ import annotations

import argparse
import asyncio
import json

from app.services.kapso_client import KapsoClient

DEFAULT_TEXT = "Hello — this message was sent from the hackathon WhatsApp starter (Kapso)."


async def main() -> None:
    parser = argparse.ArgumentParser(description="Send a demo WhatsApp text via Kapso.")
    parser.add_argument(
        "--to",
        required=True,
        help="Your WhatsApp number in E.164 (e.g. +15551234567 — use the sandbox-registered phone).",
    )
    parser.add_argument(
        "--text",
        default=DEFAULT_TEXT,
        help=f"Message body (default: {DEFAULT_TEXT!r})",
    )
    args = parser.parse_args()

    client = KapsoClient()
    result = await client.send_whatsapp_message(args.to, args.text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
