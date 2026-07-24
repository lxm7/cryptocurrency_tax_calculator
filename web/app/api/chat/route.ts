import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  type UIMessage,
} from 'ai';

// Allow streaming responses up to 30s.
export const maxDuration = 30;

// Server-only: the browser never talks to FastAPI directly (no CORS, api stays
// internal). In compose this is http://api:8000; falls back for local `pnpm dev`.
const API = process.env.API_INTERNAL_URL ?? 'http://localhost:8000';

/**
 * Translates FastAPI's domain event stream (SSE JSON lines) into the Vercel AI
 * SDK UI Message Stream Protocol. This is the ONLY place that knows the AI SDK
 * wire format — it upgrades with the `ai` package, never touching Python.
 * Week 7: add `tool_call` / `source` cases here as FastAPI emits them.
 */
export async function POST(req: Request): Promise<Response> {
  const { messages }: { messages: UIMessage[] } = await req.json();
  const last = messages[messages.length - 1];
  const text = last.parts.map((p) => (p.type === 'text' ? p.text : '')).join('');

  const upstream = await fetch(`${API}/chat`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ message: text }),
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(`Upstream error: ${upstream.status}`, { status: 502 });
  }
  const body = upstream.body;

  const stream = createUIMessageStream({
    async execute({ writer }) {
      const id = 'text-0';
      writer.write({ type: 'text-start', id });

      const reader = body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += value;

        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';
        for (const frame of frames) {
          const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
          if (!dataLine) continue;
          const event = JSON.parse(dataLine.slice(5).trim()) as {
            type: string;
            delta?: string;
          };
          if (event.type === 'text-delta' && event.delta) {
            writer.write({ type: 'text-delta', id, delta: event.delta });
          }
          // wk7: else if (event.type === 'tool_call') writer.write({ type: 'tool-input-...' })
          //      else if (event.type === 'source')    writer.write({ type: 'source-url', ... })
        }
      }

      writer.write({ type: 'text-end', id });
    },
  });

  return createUIMessageStreamResponse({ stream });
}
