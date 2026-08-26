"use client";

import { useEffect, useState } from "react";
import { API_URL, getAccessHeaders } from "@/lib/api";
import type { StreamMetricSnapshot } from "@/lib/types";

export type StreamStatus = "idle" | "connecting" | "live" | "offline";

export function useAnalyticsStream({
  metric = "mau",
  period = "last_30_days",
  enabled = true,
  onUpdate,
}: {
  metric?: string;
  period?: string;
  enabled?: boolean;
  onUpdate?: (snapshot: StreamMetricSnapshot) => void;
} = {}) {
  const [status, setStatus] = useState<StreamStatus>(enabled ? "connecting" : "idle");
  const [lastEvent, setLastEvent] = useState<StreamMetricSnapshot | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let lastEventId = "";
    let active = true;

    async function connect() {
      setStatus("connecting");
      try {
        const query = new URLSearchParams({ metric, period, max_events: "3" });
        const headers: Record<string, string> = { ...getAccessHeaders(), Accept: "text/event-stream" };
        if (lastEventId) headers["Last-Event-ID"] = lastEventId;
        const response = await fetch(`${API_URL}/stream/analytics?${query.toString()}`, {
          headers,
          signal: controller.signal,
        });
        if (!response.ok || !response.body) throw new Error(`Stream unavailable (${response.status})`);
        setStatus("live");
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (active) {
          const chunk = await reader.read();
          if (chunk.done) break;
          buffer += decoder.decode(chunk.value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const dataLine = frame.split("\n").find((line) => line.startsWith("data: "));
            if (!dataLine) continue;
            try {
              const snapshot = JSON.parse(dataLine.slice(6)) as StreamMetricSnapshot;
              lastEventId = String(snapshot.event_id);
              setLastEvent(snapshot);
              if (snapshot.type === "update") onUpdate?.(snapshot);
            } catch {
              // Ignore malformed individual frames; the next bounded reconnect
              // will establish a fresh snapshot.
            }
          }
        }
        if (active) {
          setStatus("offline");
          await new Promise<void>((resolve) => window.setTimeout(resolve, 1_000));
          if (active) await connect();
        }
      } catch {
        if (active) {
          setStatus("offline");
          await new Promise<void>((resolve) => window.setTimeout(resolve, 2_000));
          if (active) await connect();
        }
      }
    }
    void connect();
    return () => {
      active = false;
      controller.abort();
    };
  }, [enabled, metric, onUpdate, period]);

  return { status: enabled ? status : "idle", lastEvent };
}
