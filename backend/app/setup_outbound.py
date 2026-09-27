"""One-command setup for outbound phone calls (the agent calling real phones).

    docker compose exec api python -m app.setup_outbound

Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and the LiveKit keys in the environment, plus at least one
phone number in the Twilio account. It creates (or reuses) a Twilio Elastic SIP trunk with a termination
domain and credentials, then a LiveKit outbound trunk pointing at it, and prints the .env lines to add.
Safe to re-run: it replaces its own credentials and LiveKit trunk instead of piling up duplicates.
"""

import asyncio
import secrets
import string

from livekit import api
from twilio.rest import Client

from app.core.config import get_settings

TRUNK_NAME = "voicedesk-outbound"
CRED_LIST_NAME = "voicedesk-livekit"
LK_TRUNK_NAME = "voicedesk-twilio-outbound"


def _password() -> str:
    # Twilio: 12+ chars with upper, lower and a digit.
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(24))
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw) and any(c.isdigit() for c in pw):
            return pw


def setup_twilio(client: Client, account_sid: str) -> tuple[str, str, str, str]:
    numbers = client.incoming_phone_numbers.list(limit=20)
    if not numbers:
        raise SystemExit("Your Twilio account has no phone number. Buy one in the Twilio console first.")
    caller_id = get_settings().twilio_caller_id or numbers[0].phone_number

    trunk = next((t for t in client.trunking.v1.trunks.list() if t.friendly_name == TRUNK_NAME), None)
    if trunk is None:
        domain = f"voicedesk-{account_sid[-8:].lower()}.pstn.twilio.com"
        trunk = client.trunking.v1.trunks.create(friendly_name=TRUNK_NAME, domain_name=domain)
        print(f"Created Twilio SIP trunk {trunk.sid} ({trunk.domain_name})")
    else:
        print(f"Reusing Twilio SIP trunk {trunk.sid} ({trunk.domain_name})")

    # Fresh credentials each run (Twilio never reveals existing passwords).
    for cl in client.sip.credential_lists.list():
        if cl.friendly_name == CRED_LIST_NAME:
            client.sip.credential_lists(cl.sid).delete()
    username, password = f"livekit{secrets.token_hex(4)}", _password()
    cred_list = client.sip.credential_lists.create(friendly_name=CRED_LIST_NAME)
    client.sip.credential_lists(cred_list.sid).credentials.create(username=username, password=password)
    client.trunking.v1.trunks(trunk.sid).credentials_lists.create(credential_list_sid=cred_list.sid)
    print("Attached fresh SIP credentials to the trunk")
    return trunk.domain_name, username, password, caller_id


async def setup_livekit(domain: str, username: str, password: str, caller_id: str) -> str:
    s = get_settings()
    lk = api.LiveKitAPI(s.livekit_url.replace("wss://", "https://"), s.livekit_api_key, s.livekit_api_secret)
    try:
        existing = await lk.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        for t in existing.items:
            if t.name == LK_TRUNK_NAME:
                await lk.sip.delete_sip_trunk(api.DeleteSIPTrunkRequest(sip_trunk_id=t.sip_trunk_id))
        trunk = await lk.sip.create_sip_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
            name=LK_TRUNK_NAME, address=domain, numbers=[caller_id], auth_username=username, auth_password=password,
        )))
        print(f"Created LiveKit outbound trunk {trunk.sip_trunk_id}")
        return trunk.sip_trunk_id
    finally:
        await lk.aclose()


def main() -> None:
    s = get_settings()
    missing = [k for k, v in {"TWILIO_ACCOUNT_SID": s.twilio_account_sid, "TWILIO_AUTH_TOKEN": s.twilio_auth_token,
                              "LIVEKIT_API_KEY": s.livekit_api_key, "LIVEKIT_API_SECRET": s.livekit_api_secret}.items() if not v]
    if missing:
        raise SystemExit(f"Missing in .env: {', '.join(missing)}")
    client = Client(s.twilio_account_sid, s.twilio_auth_token)
    domain, username, password, caller_id = setup_twilio(client, s.twilio_account_sid)
    trunk_id = asyncio.run(setup_livekit(domain, username, password, caller_id))
    print("\nAdd these to .env, then restart (docker compose up -d):")
    print(f"LIVEKIT_OUTBOUND_TRUNK_ID={trunk_id}")
    print(f"TWILIO_CALLER_ID={caller_id}")
    print(f"TWILIO_TERMINATION_URI={domain}")
    print(f"TWILIO_TRUNK_USERNAME={username}")
    print(f"TWILIO_TRUNK_PASSWORD={password}")


if __name__ == "__main__":
    main()
