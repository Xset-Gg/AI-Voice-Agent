"""LiveKit server API: rooms, agent dispatch, SIP participants."""

import json
import uuid
from datetime import timedelta

from livekit import api

from app.core.config import get_settings
from app.core.errors import IntegrationError


def room_name_for(call_id: uuid.UUID) -> str:
    return f"call-{call_id}"


class LiveKitService:
    def _client(self) -> api.LiveKitAPI:
        s = get_settings()
        if not (s.livekit_api_key and s.livekit_api_secret):
            raise IntegrationError("LiveKit credentials are not configured")
        http_url = s.livekit_url.replace("wss://", "https://").replace("ws://", "http://")
        return api.LiveKitAPI(http_url, s.livekit_api_key, s.livekit_api_secret)

    async def start_session(self, call_id: uuid.UUID, org_id: uuid.UUID, agent_id: uuid.UUID, max_minutes: int) -> str:
        """Create the call's room and dispatch the voice agent into it before the caller arrives."""
        s = get_settings()
        room = room_name_for(call_id)
        metadata = json.dumps({"call_id": str(call_id), "org_id": str(org_id), "agent_id": str(agent_id)})
        lk = self._client()
        try:
            await lk.room.create_room(
                api.CreateRoomRequest(name=room, empty_timeout=60, departure_timeout=10, max_participants=6, metadata=metadata)
            )
            await lk.agent_dispatch.create_dispatch(
                api.CreateAgentDispatchRequest(agent_name=s.livekit_agent_name, room=room, metadata=metadata)
            )
        except api.TwirpError as e:
            raise IntegrationError(f"LiveKit error: {e.message}") from e
        finally:
            await lk.aclose()
        return room

    async def dial_out(self, room: str, to_number: str, from_number: str, max_minutes: int) -> None:
        s = get_settings()
        if not s.livekit_outbound_trunk_id:
            raise IntegrationError("LIVEKIT_OUTBOUND_TRUNK_ID is not configured")
        lk = self._client()
        try:
            await lk.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=s.livekit_outbound_trunk_id,
                    sip_call_to=to_number,
                    sip_number=from_number,
                    room_name=room,
                    participant_identity=f"sip-{to_number}",
                    participant_name="Customer",
                    krisp_enabled=True,
                )
            )
        except api.TwirpError as e:
            raise IntegrationError(f"LiveKit SIP dial failed: {e.message}") from e
        finally:
            await lk.aclose()

    def participant_token(self, room: str, identity: str, name: str, ttl_minutes: int) -> str:
        """Join token for a browser participant (dashboard test calls). Scoped to this one room."""
        s = get_settings()
        if not (s.livekit_api_key and s.livekit_api_secret):
            raise IntegrationError("LiveKit credentials are not configured")
        return (
            api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
            .with_identity(identity)
            .with_name(name)
            .with_ttl(timedelta(minutes=ttl_minutes))
            .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=False))
            .to_jwt()
        )

    async def end_session(self, room: str) -> None:
        lk = self._client()
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room))
        except api.TwirpError as e:
            if e.code != "not_found":
                raise IntegrationError(f"LiveKit error: {e.message}") from e
        finally:
            await lk.aclose()


def sip_uri_for(room: str) -> str:
    s = get_settings()
    if not s.livekit_sip_host:
        raise IntegrationError("LIVEKIT_SIP_HOST is not configured")
    # The LiveKit dispatch rule (type "callee", no prefix, randomize=false) maps the
    # dialed user part to the room name, so the caller lands in the room we prepared.
    return f"sip:{room}@{s.livekit_sip_host};transport=tcp"


livekit_service = LiveKitService()
