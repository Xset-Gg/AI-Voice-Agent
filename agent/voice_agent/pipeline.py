"""Builds the STT → LLM → TTS pipeline with provider fallbacks."""

import logging
import os

from livekit.agents import llm, stt, tts
from livekit.plugins import cartesia, deepgram, google, openai

logger = logging.getLogger("voice-agent.pipeline")


def _has(key: str) -> bool:
    return bool(os.getenv(key))


def _make_llm(model: str, temperature: float):
    if model.startswith("gemini"):
        return google.LLM(model=model, temperature=temperature, api_key=os.getenv("GEMINI_API_KEY"))
    return openai.LLM(model=model, temperature=temperature, parallel_tool_calls=False)


def build_llm(cfg: dict):
    """Primary model from the agent config; the fallback model takes over automatically if the
    primary errors or times out (e.g. OpenAI credits exhausted → Gemini)."""
    candidates = []
    for model in (cfg["llm_model"], cfg.get("fallback_llm_model")):
        if not model:
            continue
        needs = "GEMINI_API_KEY" if model.startswith("gemini") else "OPENAI_API_KEY"
        if _has(needs):
            candidates.append(_make_llm(model, cfg["temperature"]))
        else:
            logger.warning("skipping LLM %s: %s not set", model, needs)
    if not candidates:
        raise RuntimeError("No LLM available: set OPENAI_API_KEY and/or GEMINI_API_KEY")
    if len(candidates) == 1:
        return candidates[0]
    # attempt_timeout is forwarded as the request deadline; the Gemini API rejects deadlines under 10s.
    return llm.FallbackAdapter(candidates, attempt_timeout=10.0, max_retry_per_llm=0)


def build_stt(cfg: dict, vad):
    language = cfg.get("language") or "en"
    engines = []
    if _has("DEEPGRAM_API_KEY"):
        engines.append(deepgram.STT(
            model=cfg.get("stt_model") or "nova-3",
            language="multi" if language == "multi" else (language if "-" in language else f"{language}-US" if language == "en" else language),
            interim_results=True, smart_format=True, punctuate=True, filler_words=True, endpointing_ms=25,
        ))
    if _has("OPENAI_API_KEY"):
        # Non-streaming STT wrapped with VAD so it can act as a streaming fallback.
        engines.append(stt.StreamAdapter(stt=openai.STT(model="gpt-4o-transcribe", language=language.split("-")[0]), vad=vad))
    if not engines:
        raise RuntimeError("No STT available: set DEEPGRAM_API_KEY and/or OPENAI_API_KEY")
    return engines[0] if len(engines) == 1 else stt.FallbackAdapter(engines, vad=vad)


def build_tts(cfg: dict):
    provider, voice = cfg.get("tts_provider") or "openai", cfg.get("tts_voice") or "alloy"
    engines = []
    if provider == "cartesia" and _has("CARTESIA_API_KEY"):
        engines.append(cartesia.TTS(voice=voice))
    if _has("OPENAI_API_KEY"):
        openai_voice = voice if provider == "openai" else "alloy"
        engines.append(openai.TTS(
            model="gpt-4o-mini-tts", voice=openai_voice,
            instructions="Speak warmly and naturally, like a friendly receptionist on the phone. Keep a steady, relaxed pace.",
        ))
    if provider != "cartesia" and _has("CARTESIA_API_KEY"):
        engines.append(cartesia.TTS())
    if not engines:
        raise RuntimeError("No TTS available: set OPENAI_API_KEY and/or CARTESIA_API_KEY")
    return engines[0] if len(engines) == 1 else tts.FallbackAdapter(engines)


def build_turn_detection():
    """TURN_DETECTOR: multilingual (local semantic end-of-turn model, default), english, vad, or stt."""
    mode = os.getenv("TURN_DETECTOR", "multilingual")
    if mode in ("vad", "stt"):
        return mode
    try:
        if mode == "english":
            from livekit.plugins.turn_detector.english import EnglishModel

            return EnglishModel()
        from livekit.plugins.turn_detector.multilingual import MultilingualModel

        return MultilingualModel()
    except Exception as e:  # model files missing → degrade gracefully to VAD endpointing
        logger.warning("turn detector unavailable (%s); falling back to VAD", e)
        return "vad"
