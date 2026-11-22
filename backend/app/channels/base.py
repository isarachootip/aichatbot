"""Common messaging channel interface and normalized inbound event types."""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

MessageType = Literal["text", "image", "sticker", "unsupported"]


class ChannelAPIError(RuntimeError):
    """Raised when an outbound messaging platform API call fails."""


class ReplyTokenExpiredError(ChannelAPIError):
    """Raised when a LINE replyToken is expired or invalid and push fallback is needed."""


@dataclass(frozen=True)
class InboundEvent:
    """Normalized inbound customer message event across messaging platforms."""

    event_id: str
    external_user_id: str
    message_type: MessageType
    text: str | None
    reply_token: str | None
    timestamp_ms: int


@dataclass(frozen=True)
class UserProfile:
    """Basic customer profile resolved from a messaging channel."""

    external_user_id: str
    display_name: str | None = None


@runtime_checkable
class ChannelAdapter(Protocol):
    """Platform-agnostic messaging channel adapter interface (LINE, Meta, Web)."""

    def verify_signature(self, body: bytes, signature: str, secret: str) -> bool:
        """Verify inbound webhook authenticity using the channel's shared secret."""
        ...

    def parse_events(self, payload: dict[str, object]) -> list[InboundEvent]:
        """Extract normalized customer message events from a raw webhook JSON payload."""
        ...

    async def send_reply(self, reply_token: str, text: str) -> None:
        """Send a reply using an ephemeral reply token (raises ReplyTokenExpiredError)."""
        ...

    async def send_push(self, external_user_id: str, text: str) -> None:
        """Send an outbound push message directly to the customer."""
        ...

    async def get_profile(self, external_user_id: str) -> UserProfile:
        """Fetch the customer's display name for inbox visibility."""
        ...

    async def show_loading(self, external_user_id: str, seconds: int = 20) -> None:
        """Display a native chat loading indicator while generating a reply (best-effort)."""
        ...
