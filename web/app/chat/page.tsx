'use client';

import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { useState } from 'react';

export default function ChatPage() {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status } = useChat({
    transport: new DefaultChatTransport({ api: '/api/chat' }),
  });

  const busy = status === 'submitted' || status === 'streaming';

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col gap-4 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-xl font-semibold">crypto-tax-calc · chat</h1>
        <p className="text-sm text-zinc-500">
          UK crypto CGT calculation &amp; reporting aid with cited HMRC guidance.
          Read-only. Not tax advice.
        </p>
      </header>

      <div className="flex flex-1 flex-col gap-3">
        {messages.map((m) => (
          <div key={m.id} className="whitespace-pre-wrap">
            <span className="font-medium">
              {m.role === 'user' ? 'You' : 'Assistant'}:{' '}
            </span>
            {m.parts.map((p, i) =>
              p.type === 'text' ? <span key={`${m.id}-${i}`}>{p.text}</span> : null,
            )}
          </div>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!input.trim() || busy) return;
          sendMessage({ text: input });
          setInput('');
        }}
        className="flex gap-2"
      >
        <input
          className="flex-1 rounded border border-zinc-300 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-900"
          value={input}
          placeholder="How does the 30-day rule apply to these disposals?"
          onChange={(e) => setInput(e.target.value)}
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-white dark:text-zinc-900"
        >
          {busy ? '…' : 'Send'}
        </button>
      </form>
    </main>
  );
}
