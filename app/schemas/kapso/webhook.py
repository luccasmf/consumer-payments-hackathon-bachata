from pydantic import BaseModel, Field, ConfigDict

from app.schemas.kapso.message import KapsoMessage
from app.schemas.kapso.conversation import KapsoConversation


class KapsoWebhook(BaseModel):
    """Kapso inbound webhook body (message + conversation)."""

    message: KapsoMessage
    conversation: KapsoConversation
    is_new_conversation: bool
    phone_number_id: str

    model_config = ConfigDict(extra="allow")
