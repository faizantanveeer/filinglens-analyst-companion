/**
 * Typed server-sent events from POST /chat.
 *
 * EventSource can't POST or send custom headers (we need X-LLM-Key), so we read the
 * fetch body stream and parse the `event:` / `data:` frames ourselves.
 */

export type DocCitation = {
  kind: "document";
  label: string;
  chunk_id: string;
  doc_id: string;
  filename: string;
  page: number;
  section: string;
  text: string;
  score: number;
  suspicious: boolean;
};

export type WebCitation = {
  kind: "web";
  label: string;
  url: string;
  title: string;
  site: string;
  text: string;
  suspicious: boolean;
};

export type Citation = DocCitation | WebCitation;

export type ChartPoint = { x: string; y: number; label: string; page: number };
export type ChartData = {
  title: string;
  kind: "line" | "bar";
  unit: string;
  series: { name: string; points: ChartPoint[] }[];
  dropped_points: number;
};

export type AnswerType = "answer" | "web" | "not_found" | "refusal" | "out_of_scope";

export type DoneEvent = {
  answer_type: AnswerType;
  usage: { input_tokens: number; output_tokens: number; cost: number };
  cached: boolean;
  trace_id: string;
  model: string;
  route: { intent: string; complexity: string };
  verification: string;
  latency_ms: number;
  query?: string;
  deep?: boolean;
  web_reason?: string;
  web_error?: string;
  memories_used?: string[];
  key_terms?: { term: string; definition: string }[];
  calculation?: { label: string; value: number; unit: string; expression: string };
  judge?: { faithful: boolean; reason: string };
};

export type ChatEvent =
  | { event: "step"; data: { id: string; label: string } }
  | { event: "token"; data: { text: string } }
  | { event: "chart"; data: { chart: ChartData } }
  | { event: "citations"; data: { citations: Citation[] } }
  | { event: "suggestions"; data: { suggestions: string[] } }
  | { event: "done"; data: DoneEvent }
  | { event: "error"; data: { message: string } };

/** Yield parsed events from an SSE response body. */
export async function* readSSE(body: ReadableStream<Uint8Array>): AsyncGenerator<ChatEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      if (!data.length) continue;
      try {
        yield { event, data: JSON.parse(data.join("\n")) } as ChatEvent;
      } catch {
        // ignore a malformed frame rather than killing the whole answer
      }
    }
  }
}
