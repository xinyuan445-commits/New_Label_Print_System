/**
 * Browser fast path to the blg-connector's loopback API (F21).
 *
 * The assistant desktop entry forwards the central site through loopback.
 * Direct LAN/HTTPS access may also need browser local-network permission.
 * U8 printing never falls back to a server printer. Browser printing is an
 * explicit alternative when this optional assistant is unavailable.
 */

const AGENT_URL = "http://127.0.0.1:9110";
const PROBE_TIMEOUT_MS = 1500;

export type LocalAgentStatus = {
  agent: string;
  version: string;
  printers: string[];
  last_poll_ok: boolean;
  capabilities?: string[];
};

export type LocalPrinter = {
  name: string;
  host: string;
  port: number;
  /** F39: "local" = a queue discovered on the connector's computer. */
  kind?: "network" | "file" | "local";
};

export async function agentFetch<T>(
  path: string,
  init?: RequestInit,
  timeout = PROBE_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(`${AGENT_URL}${path}`, { ...init, signal: controller.signal });
    if (!response.ok) {
      const body = (await response.json().catch(() => ({}))) as { error?: string };
      throw new Error(body.error ?? `agent HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Null when no agent is reachable on this machine (the common case). */
export async function probeLocalAgent(): Promise<LocalAgentStatus | null> {
  try {
    return await agentFetch<LocalAgentStatus>("/status");
  } catch {
    return null;
  }
}

export async function fetchLocalPrinters(): Promise<LocalPrinter[]> {
  const body = await agentFetch<{ printers: LocalPrinter[] }>("/printers");
  return body.printers;
}

export async function printLocal(printer: string, zpl: string, copies: number): Promise<void> {
  await agentFetch(
    "/print",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ printer, zpl, copies }),
    },
    310_000,
  );
}
