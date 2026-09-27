"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, liveSocketUrl } from "./api";
import type { LiveMessage } from "./types";

/** Fetch-on-mount with reload + error state. */
export function useApi<T>(path: string | null, query?: Record<string, string | number | boolean | undefined | null>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
  const key = path ? path + JSON.stringify(query ?? {}) : null;

  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api<T>(path, { query }));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    load();
  }, [load]);

  return { data, error, loading, reload: load, setData };
}

/** Subscribe to the organization's live call events with automatic reconnect. */
export function useLiveEvents(onMessage: (m: LiveMessage) => void) {
  const handler = useRef(onMessage);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    handler.current = onMessage;
  });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 0;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;

    const connect = () => {
      const url = liveSocketUrl();
      if (!url || closed) return;
      ws = new WebSocket(url);
      ws.onopen = () => {
        retry = 0;
        setConnected(true);
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
      };
      ws.onmessage = (e) => {
        try {
          handler.current(JSON.parse(e.data));
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        clearInterval(ping);
        if (!closed) timer = setTimeout(connect, Math.min(1000 * 2 ** retry++, 15000));
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(ping);
      ws?.close();
    };
  }, []);

  return connected;
}

/** Re-render every `ms` (for live timers). */
export function useTick(ms = 1000) {
  const [, set] = useState(0);
  useEffect(() => {
    const t = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(t);
  }, [ms]);
}
