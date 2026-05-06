"""
Inbound WhatsApp handling: reply to users via Kapso.

Default demo replies with a fixed template that quotes what they sent. Replace
``handle_inbound`` with LLM flows, payments, or state machines — keep it async.
"""

from app.schemas.kapso import KapsoMessage
from app.services.kapso_client import KapsoClient
from app.services.rates_service import (
    handle_rates_message,
    is_awaiting_rates_input,
    is_rates_request,
)

_HELP_TRIGGERS: frozenset[str] = frozenset(
    {
        "ayuda",
        "help",
        "/ayuda",
        "/help",
        "comandos",
        "menu",
        "info",
    }
)

HELP_MESSAGE = (
    "📖 *Help*\n\n"
    "*What you can do*\n"
    "• *FX quotes:* send keywords like *rate*, *rates*, *fx*, *exchange*, "
    "or *tasa* / *cotización* / *tipo de cambio*. I'll ask for a destination "
    "country and an amount in *USD* to compare sample quotes across "
    "providers.\n"
    "• *Demo mode:* any other text message gets a short demonstration "
    "reply.\n\n"
    "*What I can't do*\n"
    "• I can't send money or complete transfers—this is information only.\n"
    "• I don't store bank details or process payments in this chat.\n"
    "• Quotes are for side-by-side comparison; each provider sets the "
    "final price.\n\n"
    "_Send *help* (or *ayuda*) anytime to see this again._"
)


def is_help_request(text: str | None) -> bool:
    """True if the user is explicitly asking for the help text."""
    if not text:
        return False
    first = text.strip().lower().split(maxsplit=1)[0]
    first = first.rstrip("?!.")
    return first in _HELP_TRIGGERS


def inbound_text(msg: KapsoMessage) -> str | None:
    """Best-effort text or button title from an inbound Kapso/WA message."""
    if msg.type == "text" and msg.text:
        return msg.text.body
    if msg.interactive:
        button_reply = msg.interactive.get("button_reply") or {}
        list_reply = msg.interactive.get("list_reply") or {}
        if button_reply:
            return button_reply.get("title") or button_reply.get("id")
        if list_reply:
            return list_reply.get("title") or list_reply.get("id")
    if msg.button:
        return msg.button.get("text") or msg.button.get("payload")
    if msg.kapso.content:
        return msg.kapso.content
    return None


def _reply_body_for_demo(user_payload: str | None, message_type: str) -> str:
    if user_payload:
        quoted = user_payload
    else:
        quoted = f"a {message_type} message (send text for a full quote)"
    return f"I just received: {quoted}. Lets start building 🚀"


async def handle_inbound(msg: KapsoMessage, client: KapsoClient) -> None:
    """
    Called for each *inbound* message after webhook verification.

    ``msg.phone_number`` is the user to reply to (same format Kapso expects for ``to``).
    """
    text = inbound_text(msg)

    if is_help_request(text):
        body = HELP_MESSAGE
    elif is_rates_request(text) or is_awaiting_rates_input(msg.phone_number):
        body = await handle_rates_message(msg.phone_number, text)
    else:
        body = _reply_body_for_demo(text, msg.type)

    await client.send_whatsapp_message(msg.phone_number, body)
