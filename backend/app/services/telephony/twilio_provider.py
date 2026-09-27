import anyio
from twilio.base.exceptions import TwilioRestException
from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Dial, VoiceResponse

from app.core.config import Settings
from app.core.errors import IntegrationError
from app.services.telephony.base import ProviderNumber, TelephonyProvider


class TwilioProvider(TelephonyProvider):
    name = "twilio"

    def __init__(self, settings: Settings):
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise IntegrationError("Twilio credentials are not configured")
        self.settings = settings
        self.client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self.validator = RequestValidator(settings.twilio_auth_token)

    def validate_request(self, url: str, params: dict, signature: str | None) -> bool:
        if not self.settings.twilio_validate_signatures:
            return True
        return bool(signature) and self.validator.validate(url, params, signature)

    def bridge_to_sip(self, sip_uri: str, action_url: str, status_url: str) -> str:
        resp = VoiceResponse()
        # answerOnBridge keeps the caller hearing ringback until the agent's SIP leg answers,
        # so billing and "answered" semantics match what the caller experiences.
        dial = Dial(answer_on_bridge=True, action=action_url, method="POST", timeout=20)
        dial.sip(
            sip_uri,
            username=self.settings.twilio_sip_username,
            password=self.settings.twilio_sip_password,
            status_callback=status_url,
            status_callback_event="initiated ringing answered completed",
        )
        resp.append(dial)
        return str(resp)

    def reject(self, message: str) -> str:
        resp = VoiceResponse()
        resp.say(message)
        resp.hangup()
        return str(resp)

    async def _run(self, fn):
        try:
            return await anyio.to_thread.run_sync(fn)
        except TwilioRestException as e:
            raise IntegrationError(f"Twilio error {e.code}: {e.msg}") from e

    async def transfer(self, call_sid: str, to_number: str, announcement: str) -> None:
        resp = VoiceResponse()
        if announcement:
            resp.say(announcement)
        resp.dial(to_number, timeout=30)
        twiml = str(resp)
        await self._run(lambda: self.client.calls(call_sid).update(twiml=twiml))

    async def hangup(self, call_sid: str) -> None:
        await self._run(lambda: self.client.calls(call_sid).update(status="completed"))

    async def list_numbers(self) -> list[ProviderNumber]:
        def go():
            return [
                ProviderNumber(sid=n.sid, e164=n.phone_number, friendly_name=n.friendly_name or "", voice_url=n.voice_url)
                for n in self.client.incoming_phone_numbers.list(limit=200)
            ]

        return await self._run(go)

    async def configure_number(self, sid: str, voice_url: str, status_url: str) -> None:
        await self._run(
            lambda: self.client.incoming_phone_numbers(sid).update(
                voice_url=voice_url, voice_method="POST", status_callback=status_url, status_callback_method="POST"
            )
        )
