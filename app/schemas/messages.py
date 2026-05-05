from pydantic import BaseModel, Field


class SendTextRequest(BaseModel):
    to: str = Field(description="Recipient E.164, e.g. +15551234567")
    text: str = Field(description="Message body")


class MessageResponse(BaseModel):
    success: bool
    message_id: str | None = None
    error: str | None = None
