"use client";

import clsx from "clsx";
import { Mic, MicOff, PhoneCall, PhoneOff, Smartphone } from "lucide-react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useLiveEvents } from "@/lib/hooks";
import type { AgentConfig, CallSummary, Segment } from "@/lib/types";
import { Transcript } from "./CallTimeline";
import { Button, ErrorBox, Field, Input, Modal, Tabs } from "./ui";

type Phase = "idle" | "connecting" | "waiting" | "live" | "ended";
type Mode = "browser" | "phone";

const AGENT_STATE_LABEL: Record<string, string> = {
  initializing: "Getting ready…", listening: "Listening", thinking: "Thinking…", speaking: "Speaking",
};

/** Talk to an agent from the browser microphone — same pipeline and tools as a real phone call. */
export function TestCall({ agent, open, onClose }: { agent: AgentConfig; open: boolean; onClose: () => void }) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("browser");
  const [callerPhone, setCallerPhone] = useState("+15550100000");
  const [myPhone, setMyPhone] = useState("");
  const [callId, setCallId] = useState<string | null>(null);
  const [segments, setSegments] = useState<Pick<Segment, "id" | "role" | "text" | "interrupted" | "created_at">[]>([]);
  const [agentState, setAgentState] = useState<string>("initializing");
  const [muted, setMuted] = useState(false);
  const room = useRef<Room | null>(null);
  const audioBox = useRef<HTMLDivElement>(null);

  useLiveEvents((m) => {
    if (!callId || m.call_id !== callId) return;
    const d = m.data;
    if (m.type === "transcript") {
      setSegments((prev) => prev.some((s) => s.id === d.segment_id) ? prev : [...prev, {
        id: String(d.segment_id), role: d.role as "user" | "assistant", text: String(d.text), interrupted: !!d.interrupted,
        created_at: String(d.at ?? new Date().toISOString()),
      }]);
    } else if (m.type === "agent_state") {
      setAgentState(String(d.state));
    } else if (m.type === "status" && d.status === "in_progress") {
      setPhase("live");
    } else if (m.type === "status" && ["completed", "transferred", "failed", "no_answer"].includes(String(d.status))) {
      if (d.status === "no_answer") setError("The phone wasn't answered.");
      setPhase("ended");
      room.current?.disconnect();
    } else if (m.type === "error" && d.recoverable === false) {
      setError(`Agent error: ${String(d.error ?? "unknown")}`);
    }
  });

  // Always release the microphone and leave the room when the dialog goes away.
  useEffect(() => () => { room.current?.disconnect(); }, []);

  const start = async () => {
    setError(null);
    setSegments([]);
    setAgentState("initializing");
    setPhase("connecting");
    try {
      const res = await api<{ call: CallSummary; url: string | null; token: string | null }>("/calls/test", {
        body: mode === "phone"
          ? { agent_id: agent.id, dial_number: myPhone.replace(/[\s\-().]/g, "") }
          : { agent_id: agent.id, caller_phone: callerPhone },
      });
      setCallId(res.call.id);
      if (!res.url || !res.token) {
        setPhase("waiting"); // the agent is ringing the phone; live events take it from here
        return;
      }
      const r = new Room({ adaptiveStream: true, dynacast: true, audioCaptureDefaults: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      room.current = r;
      r.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          audioBox.current?.appendChild(el);
          setPhase("live");
        }
      });
      r.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => track.detach().forEach((el) => el.remove()));
      r.on(RoomEvent.ParticipantConnected, () => setPhase((p) => (p === "waiting" ? "live" : p)));
      r.on(RoomEvent.Disconnected, () => setPhase((p) => (p === "idle" ? p : "ended")));
      await r.connect(res.url, res.token);
      await r.startAudio();
      await r.localParticipant.setMicrophoneEnabled(true);
      setMuted(false);
      setPhase(r.remoteParticipants.size ? "live" : "waiting");
    } catch (e) {
      const msg = (e as Error).message;
      setError(/permission|NotAllowed/i.test(msg) ? "Microphone access was blocked. Allow the microphone for this site and try again." : msg);
      room.current?.disconnect();
      setPhase("idle");
    }
  };

  const hangUp = async () => {
    room.current?.disconnect();
    setPhase("ended");
    if (callId) api(`/calls/${callId}/hangup`, { method: "POST" }).catch(() => { /* already ended by the agent */ });
  };

  const toggleMute = async () => {
    if (!room.current) return;
    await room.current.localParticipant.setMicrophoneEnabled(muted);
    setMuted(!muted);
  };

  const close = () => {
    if (phase === "connecting" || phase === "waiting" || phase === "live") hangUp();
    setPhase("idle");
    setCallId(null);
    onClose();
  };

  const inCall = phase === "connecting" || phase === "waiting" || phase === "live";

  return (
    <Modal open={open} onClose={close} title={`Test call · ${agent.name}`} wide
      footer={inCall ? (
        <>
          {mode === "browser" && (
            <Button onClick={toggleMute} disabled={phase === "connecting"}>{muted ? <MicOff className="size-4" /> : <Mic className="size-4" />} {muted ? "Unmute" : "Mute"}</Button>
          )}
          <Button variant="danger" onClick={hangUp}><PhoneOff className="size-4" /> Hang up</Button>
        </>
      ) : (
        <>
          <Button onClick={close}>Close</Button>
          <Button variant="primary" onClick={start} disabled={mode === "phone" && !myPhone.trim()}>
            {mode === "phone" ? <Smartphone className="size-4" /> : <PhoneCall className="size-4" />}
            {phase === "ended" ? "Call again" : mode === "phone" ? "Call my phone" : "Start call"}
          </Button>
        </>
      )}>
      <div className="space-y-4">
        {error && <ErrorBox message={error} />}
        {phase === "idle" && (
          <>
            <Tabs<Mode> value={mode} onChange={setMode} items={[{ value: "browser", label: "Talk in browser" }, { value: "phone", label: "Call my phone" }]} />
            {mode === "browser" ? (
              <>
                <p className="text-sm text-ink-2">
                  Talk to your agent through your microphone. It uses the same voice, knowledge base and booking tools as a real phone call,
                  and the call is saved in Call History.
                </p>
                <Field label="Pretend to call from" hint="The agent books and looks up appointments under this number.">
                  <Input value={callerPhone} onChange={(e) => setCallerPhone(e.target.value)} />
                </Field>
              </>
            ) : (
              <>
                <p className="text-sm text-ink-2">
                  The agent will ring your phone. Pick up and talk to it like a customer would. The call is saved in Call History.
                </p>
                <Field label="Your phone number" hint="Include the country code, e.g. +974 5555 1234.">
                  <Input type="tel" autoComplete="tel" placeholder="+974…" value={myPhone} onChange={(e) => setMyPhone(e.target.value)} />
                </Field>
              </>
            )}
          </>
        )}
        {phase !== "idle" && (
          <div className="flex items-center gap-3 rounded-lg bg-surface-2 px-4 py-3 text-sm">
            <span className={clsx("size-2.5 rounded-full", phase === "live" ? "live-dot bg-good" : phase === "ended" ? "bg-ink-3" : "animate-pulse bg-warn")} />
            <span className="font-medium">
              {phase === "connecting" && "Connecting…"}
              {phase === "waiting" && (mode === "phone" ? `Ringing ${myPhone}…` : "Waiting for the agent to join…")}
              {phase === "live" && (AGENT_STATE_LABEL[agentState] ?? "Connected")}
              {phase === "ended" && "Call ended"}
            </span>
            {phase === "live" && <span className="text-ink-3">· {mode === "phone" ? "talk on your phone" : "speak normally, the agent will answer"}</span>}
          </div>
        )}
        {phase !== "idle" && (
          <div className="max-h-[50vh] overflow-y-auto rounded-lg border border-line">
            <Transcript segments={segments} live={inCall} />
          </div>
        )}
        <div ref={audioBox} className="hidden" />
      </div>
    </Modal>
  );
}
