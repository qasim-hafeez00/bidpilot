import { useEffect, useState } from "react";

export type RunEvent = {
  node: string; ts?: string; status?: string; trace?: Record<string, unknown>; attention?: string;
  usage?: Array<Record<string, unknown>>; interrupt?: boolean; trace_url?: string; error?: string;
};

/** Live node-by-node progress over Server-Sent Events (tails persisted LangGraph stream events). */
export function useRunStream(runId?: string | null) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [done, setDone] = useState<RunEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!runId) return;
    setEvents([]); setDone(null); setError(null);
    const es = new EventSource(`/api/runs/${runId}/stream`, { withCredentials: true });
    es.addEventListener("node", (e) => setEvents((xs) => [...xs, JSON.parse((e as MessageEvent).data)]));
    es.addEventListener("end", (e) => { setDone(JSON.parse((e as MessageEvent).data)); es.close(); });
    es.onerror = () => setError("stream interrupted - reconnecting");
    return () => es.close();
  }, [runId]);
  return { events, done, error };
}
