"""One-time LiveKit SIP setup for Twilio.

    python setup_livekit_sip.py

Creates:
  * an inbound SIP trunk that accepts calls from Twilio, authenticated with
    TWILIO_SIP_USERNAME / TWILIO_SIP_PASSWORD (the same credentials the backend puts in <Dial><Sip>),
  * a "callee" dispatch rule that routes each call into the room named by the SIP URI user part
    (the backend dials sip:call-<id>@LIVEKIT_SIP_HOST, so the caller lands in call-<id>),
  * optionally an outbound trunk to your Twilio Elastic SIP Trunk for outbound calls/transfers
    (set TWILIO_TERMINATION_URI, e.g. my-trunk.pstn.twilio.com, plus TWILIO_TRUNK_USERNAME/PASSWORD).
Prints the ids to put in your .env.
"""

import asyncio
import os

from dotenv import load_dotenv
from livekit import api

load_dotenv()


async def main() -> None:
    url = os.environ["LIVEKIT_URL"].replace("wss://", "https://").replace("ws://", "http://")
    lk = api.LiveKitAPI(url, os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
    try:
        user, pw = os.environ["TWILIO_SIP_USERNAME"], os.environ["TWILIO_SIP_PASSWORD"]
        inbound = await lk.sip.create_sip_inbound_trunk(api.CreateSIPInboundTrunkRequest(trunk=api.SIPInboundTrunkInfo(
            name="twilio-inbound", auth_username=user, auth_password=pw, krisp_enabled=True,
        )))
        print(f"Inbound trunk:  {inbound.sip_trunk_id}")

        rule = await lk.sip.create_sip_dispatch_rule(api.CreateSIPDispatchRuleRequest(dispatch_rule=api.SIPDispatchRuleInfo(
            name="route-to-call-room",
            trunk_ids=[inbound.sip_trunk_id],
            rule=api.SIPDispatchRule(dispatch_rule_callee=api.SIPDispatchRuleCallee(room_prefix="", randomize=False)),
        )))
        print(f"Dispatch rule:  {rule.sip_dispatch_rule_id}")

        if term := os.getenv("TWILIO_TERMINATION_URI"):
            numbers = [n.strip() for n in os.getenv("TWILIO_OUTBOUND_NUMBERS", "").split(",") if n.strip()]
            outbound = await lk.sip.create_sip_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=api.SIPOutboundTrunkInfo(
                name="twilio-outbound", address=term, numbers=numbers or ["*"],
                auth_username=os.getenv("TWILIO_TRUNK_USERNAME", ""), auth_password=os.getenv("TWILIO_TRUNK_PASSWORD", ""),
            )))
            print(f"Outbound trunk: {outbound.sip_trunk_id}   -> set LIVEKIT_OUTBOUND_TRUNK_ID")
    finally:
        await lk.aclose()


if __name__ == "__main__":
    asyncio.run(main())
