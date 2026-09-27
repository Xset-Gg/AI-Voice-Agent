from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderNumber:
    sid: str
    e164: str
    friendly_name: str
    voice_url: str | None


class TelephonyProvider(ABC):
    """Adapter interface for carriers. Twilio is the first implementation; Telnyx/Vonage/etc.
    can be added by implementing this and registering it in get_telephony()."""

    name: str

    @abstractmethod
    def validate_request(self, url: str, params: dict, signature: str | None) -> bool:
        """Verify a webhook genuinely came from the carrier."""

    @abstractmethod
    def bridge_to_sip(self, sip_uri: str, action_url: str, status_url: str) -> str:
        """Webhook response that connects the PSTN caller to the voice session's SIP endpoint."""

    @abstractmethod
    def reject(self, message: str) -> str:
        """Webhook response that plays a message and hangs up."""

    @abstractmethod
    async def transfer(self, call_sid: str, to_number: str, announcement: str) -> None:
        """Move a live call to a human at `to_number`."""

    @abstractmethod
    async def hangup(self, call_sid: str) -> None: ...

    @abstractmethod
    async def list_numbers(self) -> list[ProviderNumber]: ...

    @abstractmethod
    async def configure_number(self, sid: str, voice_url: str, status_url: str) -> None:
        """Point a carrier phone number's voice webhook at this platform."""
