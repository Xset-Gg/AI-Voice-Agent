from app.core.config import get_settings
from app.services.telephony.base import ProviderNumber, TelephonyProvider

_provider: TelephonyProvider | None = None


def get_telephony() -> TelephonyProvider:
    global _provider
    if _provider is None:
        from app.services.telephony.twilio_provider import TwilioProvider

        _provider = TwilioProvider(get_settings())
    return _provider


def set_telephony(provider: TelephonyProvider | None) -> None:
    global _provider
    _provider = provider


__all__ = ["ProviderNumber", "TelephonyProvider", "get_telephony", "set_telephony"]
