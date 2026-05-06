from pydantic import BaseModel, Field, field_validator


class MonitoCompareRequest(BaseModel):
    """Body for comparing Monito transfer quotes (US → destination by default)."""

    country: str = Field(description="Recipient country ISO 3166-1 alpha-2, e.g. mx, co")
    amount: float = Field(gt=0, description="Send amount in send_currency (default USD)")
    receive_currency: str | None = Field(
        default=None,
        description="Override receive currency ISO 4217 (e.g. mxn); inferred from country if omitted",
    )
    top: int = Field(default=0, ge=0, description="Cap number of provider rows (0 = all)")

    @field_validator("country")
    @classmethod
    def normalize_country(cls, v: str) -> str:
        s = v.strip().lower()
        if len(s) != 2 or not s.isalpha():
            raise ValueError("country must be a 2-letter alphabetic ISO code")
        return s

    @field_validator("receive_currency")
    @classmethod
    def normalize_receive_currency(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        s = v.strip().lower()
        if len(s) != 3 or not s.isalpha():
            raise ValueError("receive_currency must be a 3-letter alphabetic ISO code")
        return s
