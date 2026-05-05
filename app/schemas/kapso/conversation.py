from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class KapsoConversationMeta(BaseModel):
    messages_count: int = Field(default=0)
    last_message_id: str | None = None
    last_message_type: str | None = None
    last_message_timestamp: str | None = None
    last_message_text: str | None = None
    last_inbound_at: str | None = None

    model_config = ConfigDict(extra="allow")


class KapsoConversation(BaseModel):
    id: str
    phone_number: str
    status: str
    contact_name: str | None = None
    kapso: KapsoConversationMeta = Field(default_factory=KapsoConversationMeta)
    phone_number_id: str | None = None
    last_active_at: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")
