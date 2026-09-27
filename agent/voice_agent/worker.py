"""LiveKit voice agent worker.

    python -m voice_agent.worker download-files   # once: VAD + turn-detector models
    python -m voice_agent.worker dev              # local development
    python -m voice_agent.worker start            # production

The backend creates a room per call and explicitly dispatches this agent into it with
{"call_id": ...} metadata; the phone caller joins the same room over SIP.
"""

import asyncio
import json
import logging
import os
import time

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatMessage,
    JobContext,
    JobProcess,
    StopResponse,
    TurnHandlingOptions,
    cli,
    metrics,
)
from livekit.agents.voice import room_io
from livekit.plugins import silero

from voice_agent.backend import BackendClient
from voice_agent.pipeline import build_llm, build_stt, build_tts, build_turn_detection
from voice_agent.tools import build_tools

load_dotenv()
logger = logging.getLogger("voice-agent")

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "")
AGENT_NAME = os.getenv("LIVEKIT_AGENT_NAME", "voice-agent")


class CallState:
    """Per-call state shared by event handlers and tools."""

    def __init__(self, ctx: JobContext, backend: BackendClient, data: dict):
        self.ctx = ctx
        self.backend = backend
        self.data = data
        self.cfg = data["agent"]
        self.session: AgentSession | None = None
        self.participant: rtc.RemoteParticipant | None = None
        self.end_reason = "caller_hangup"
        self.ending = False
        self.away_strikes = 0
        self.started = time.monotonic()
        # latency bookkeeping keyed by speech_id
        self._turn: dict[str, dict] = {}
        self.latencies: list[float] = []
        self.interruptions = 0
        self.user_turns = 0
        self.usage = metrics.UsageCollector()

    # ----- escalation -----

    async def failed_turn(self, kind: str) -> str | None:
        """Record a turn the agent couldn't satisfy; returns guidance for the LLM when the
        business's fallback policy says it's time to offer a human."""
        try:
            res = await self.backend.event("failed_turn", {"kind": kind})
        except Exception:
            return None
        if (
            res.get("failed_turns", 0) >= self.cfg["max_failed_turns"]
            and "repeated_failure" in self.cfg["transfer_triggers"]
            and self.cfg["transfer_enabled"]
        ):
            return "You have been unable to help several times in this call. Apologise and offer to transfer the caller to a team member."
        return None

    async def transfer(self, reason: str) -> str:
        if not self.cfg["transfer_enabled"]:
            return json.dumps({"ok": False, "error": "Transfers are not available. Offer to take a message instead."})
        res = await self.backend.tool("transfer_to_human", {"reason": reason})
        if not res.get("ok"):
            return json.dumps(res)
        self.end_reason = f"transferred:{reason}"
        if res.get("method") == "sip_refer" and self.participant is not None:
            try:
                await self.ctx.transfer_sip_participant(self.participant, res["transfer_to"])
            except Exception as e:
                logger.exception("SIP transfer failed")
                self.backend.emit("error", {"stage": "transfer", "error": str(e)[:300]})
                return json.dumps({"ok": False, "error": "The transfer didn't go through. Apologise and offer to take a message."})
        # carrier_redirect: Twilio has already moved the caller; our SIP leg is ending.
        self.ending = True
        raise StopResponse()

    async def hangup(self, reason: str) -> None:
        if self.ending:
            return
        self.ending = True
        self.end_reason = reason
        # Deleting the room disconnects the SIP participant, which hangs up the phone call.
        await self.ctx.delete_room()

    # ----- metrics -----

    def on_metrics(self, m) -> None:
        self.usage.collect(m)
        sid = getattr(m, "speech_id", None)
        if isinstance(m, metrics.EOUMetrics) and sid:
            self._turn.setdefault(sid, {})["eou"] = m.end_of_utterance_delay
        elif isinstance(m, metrics.LLMMetrics) and sid and not m.cancelled:
            self._turn.setdefault(sid, {})["llm"] = m.ttft
        elif isinstance(m, metrics.TTSMetrics) and sid and not m.cancelled:
            self._turn.setdefault(sid, {})["tts"] = m.ttfb
        else:
            return
        t = self._turn.get(sid, {})
        if {"eou", "llm", "tts"} <= t.keys():
            # Perceived response latency: end of caller speech → first agent audio.
            total_ms = (t["eou"] + t["llm"] + t["tts"]) * 1000
            self.latencies.append(total_ms)
            self._turn.pop(sid, None)
            self.backend.emit("metrics", {"response_latency_ms": round(total_ms), "eou_ms": round(t["eou"] * 1000),
                                          "llm_ttft_ms": round(t["llm"] * 1000), "tts_ttfb_ms": round(t["tts"] * 1000)})

    def summary_metrics(self) -> dict:
        lat = sorted(self.latencies)
        usage = self.usage.get_summary()
        return {
            "avg_response_latency_ms": round(sum(lat) / len(lat)) if lat else None,
            "p95_response_latency_ms": round(lat[int(len(lat) * 0.95) - 1]) if len(lat) >= 5 else None,
            "turns": self.user_turns,
            "interruptions": self.interruptions,
            "agent_seconds": round(time.monotonic() - self.started),
            "usage": {k: v for k, v in (usage.__dict__ if hasattr(usage, "__dict__") else {}).items() if isinstance(v, (int, float))},
        }


class VoiceAgent(Agent):
    def __init__(self, state: CallState):
        super().__init__(instructions=state.data["system_prompt"], tools=build_tools(state))
        self.state = state

    async def on_enter(self) -> None:
        d = self.state.data
        if d["direction"] == "outbound":
            await self.session.generate_reply(instructions=(
                f"You placed this outbound call on behalf of {d['business_name']}. Purpose: {d['outbound_purpose'] or 'follow up with the customer'}. "
                "Greet the person, say who you are and why you're calling, in one or two sentences."
            ))
        else:
            await self.session.say(d["greeting"], allow_interruptions=True)


async def _wait_until_answered(ctx: JobContext, participant: rtc.RemoteParticipant, timeout: float) -> bool:
    """For outbound SIP calls: wait for sip.callStatus == "active" (answered). False if it hangs up or times out."""
    answered = asyncio.get_running_loop().create_future()

    def check(p: rtc.Participant) -> None:
        if p.identity != participant.identity or answered.done():
            return
        status = p.attributes.get("sip.callStatus")
        if status == "active":
            answered.set_result(True)
        elif status == "hangup":
            answered.set_result(False)

    def left(p: rtc.RemoteParticipant) -> None:
        if p.identity == participant.identity and not answered.done():
            answered.set_result(False)

    ctx.room.on("participant_attributes_changed", lambda _changed, p: check(p))
    ctx.room.on("participant_disconnected", left)
    check(participant)
    try:
        return await asyncio.wait_for(answered, timeout)
    except asyncio.TimeoutError:
        return False


def prewarm(proc: JobProcess) -> None:
    # Loaded once per worker process so calls don't pay model-load latency.
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=0.35, activation_threshold=0.5, sample_rate=16000)


server = AgentServer(setup_fnc=prewarm)


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    meta = json.loads(ctx.job.metadata or ctx.job.room.metadata or "{}")
    call_id = meta.get("call_id")
    if not call_id:
        logger.error("job without call_id metadata; refusing")
        return
    ctx.log_context_fields = {"call_id": call_id}
    backend = BackendClient(BACKEND_URL, INTERNAL_API_TOKEN, call_id)
    try:
        data = await backend.context()
    except Exception:
        logger.exception("could not load call context")
        await backend.aclose()
        return

    state = CallState(ctx, backend, data)
    cfg = state.cfg
    await ctx.connect()
    participant = await ctx.wait_for_participant()
    state.participant = participant
    if data["direction"] == "outbound" and participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        # The SIP participant joins while the phone is still ringing; don't greet an unanswered phone.
        if not await _wait_until_answered(ctx, participant, timeout=45):
            logger.info("outbound call not answered")
            await backend.end("no_answer", {})
            await backend.aclose()
            ctx.shutdown(reason="no_answer")
            return
    await backend.answered()

    vad = ctx.proc.userdata["vad"]
    session = AgentSession(
        vad=vad,
        stt=build_stt(cfg, vad),
        llm=build_llm(cfg),
        tts=build_tts(cfg),
        turn_handling=TurnHandlingOptions(
            turn_detection=build_turn_detection(),
            endpointing={"min_delay": cfg["min_endpointing_delay"], "max_delay": cfg["max_endpointing_delay"]},
            interruption={
                "enabled": cfg["allow_interruptions"],
                "min_duration": 0.5,       # ignore coughs / short noises
                "min_words": 1,            # ...and require at least a word when STT is available
                "resume_false_interruption": True,
                "false_interruption_timeout": 1.5,
            },
            preemptive_generation={"enabled": True},  # start the LLM before end-of-turn is final
        ),
        user_away_timeout=float(cfg["silence_timeout_seconds"]),
        max_tool_steps=4,
    )
    state.session = session

    # ----- event wiring (handlers must be sync; heavy work goes to tasks) -----

    @session.on("conversation_item_added")
    def _item(ev):
        item = ev.item
        if not isinstance(item, ChatMessage) or item.role not in ("user", "assistant"):
            return
        text = (item.text_content or "").strip()
        if not text:
            return
        if item.role == "user":
            state.user_turns += 1
            state.away_strikes = 0
        if item.interrupted:
            state.interruptions += 1
            backend.emit("interruption", {"partial_text": text[:300]})
        backend.transcript(item.role, text, interrupted=bool(item.interrupted), confidence=item.transcript_confidence)

    @session.on("agent_state_changed")
    def _agent_state(ev):
        backend.emit("agent_state", {"state": ev.new_state})

    @session.on("user_state_changed")
    def _user_state(ev):
        backend.emit("user_state", {"state": ev.new_state})
        if ev.new_state == "away" and not state.ending:
            asyncio.create_task(_handle_silence())

    async def _handle_silence():
        state.away_strikes += 1
        backend.emit("silence", {"strike": state.away_strikes, "timeout_s": cfg["silence_timeout_seconds"]})
        if state.away_strikes == 1:
            session.generate_reply(instructions="The caller has gone quiet. Briefly and kindly check whether they're still there.")
        else:
            handle = session.say("I haven't heard anything for a while, so I'll let you go. Feel free to call back anytime. Goodbye!",
                                 allow_interruptions=False)
            await handle.wait_for_playout()
            await state.hangup("silence_timeout")

    @session.on("metrics_collected")
    def _metrics(ev):
        state.on_metrics(ev.metrics)

    @session.on("error")
    def _error(ev):
        err = ev.error
        recoverable = getattr(err, "recoverable", True)
        backend.emit("error", {"source": type(ev.source).__name__, "error": str(err)[:300], "recoverable": recoverable})
        if not recoverable and not state.ending:
            asyncio.create_task(_fatal_fallback())

    async def _fatal_fallback():
        """The AI pipeline is broken mid-call: hand the caller to a human if allowed, else apologise."""
        if cfg["transfer_enabled"]:
            try:
                await state.transfer("tool_error")
            except StopResponse:
                return
            except Exception:
                logger.exception("fallback transfer failed")
        await state.hangup("pipeline_error")

    async def _max_duration_guard():
        limit = cfg["max_call_minutes"] * 60
        await asyncio.sleep(max(limit - 30, 10))
        if state.ending:
            return
        session.generate_reply(instructions="The call is about to reach its time limit. Politely wrap up in one sentence.")
        await asyncio.sleep(30)
        if not state.ending:
            await state.hangup("max_duration")

    guard = asyncio.create_task(_max_duration_guard())

    async def _finalize(reason: str = "") -> None:
        guard.cancel()
        if state.end_reason == "caller_hangup" and reason:
            state.end_reason = reason
        try:
            await backend.end(state.end_reason, state.summary_metrics())
        except Exception:
            logger.exception("failed to report call end")
        await backend.aclose()

    ctx.add_shutdown_callback(_finalize)

    await session.start(
        agent=VoiceAgent(state),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            participant_identity=participant.identity,
            close_on_disconnect=True,
            delete_room_on_close=True,
        ),
    )


if __name__ == "__main__":
    cli.run_app(server)
