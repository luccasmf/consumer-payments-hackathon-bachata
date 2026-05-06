"""Tests for inbound bot helpers (no Kapso / network)."""

import pytest

from app.bot import HELP_MESSAGE, is_help_request


class TestHelpCommand:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("ayuda", True),
            ("Ayuda", True),
            ("AYUDA!", True),
            ("ayuda por favor", True),
            ("help", True),
            ("/help", True),
            ("/ayuda", True),
            ("comandos", True),
            ("menu", True),
            ("info", True),
            ("", False),
            (None, False),
            ("Mexico 250", False),
            ("tasa", False),
        ],
    )
    def test_is_help_request(self, text: str | None, expected: bool) -> None:
        assert is_help_request(text) is expected

    def test_help_message_is_non_empty_english(self) -> None:
        assert "Help" in HELP_MESSAGE
        assert "USD" in HELP_MESSAGE
