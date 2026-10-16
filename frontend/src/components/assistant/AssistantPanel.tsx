"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Button, Dialog, ErrorState, LoadingBlock, Notice, cx } from "@/components/ui";
import { useToast } from "@/components/Toast";
import { endpoints } from "@/lib/endpoints";
import { describeError, useApiQuery } from "@/lib/hooks";
import type { ChatMessageOut, ChatOut } from "@/lib/types";

const MAX_CHARS = 8000;

const SUGGESTIONS = {
  household: [
    "When does this household first run short of cash, and why?",
    "Which approved terms limit liquidity the most?",
    "What is still awaiting review, and could it change the results?",
  ],
  general: [
    "How do interval fund repurchase offers work?",
    "What does a blind-spot check show?",
    "How do I get extracted terms approved?",
  ],
};

/** `/households/<uuid>/...` -> the household id; anything else -> null (general conversation). */
export function householdIdFromPath(pathname: string): string | null {
  return /^\/households\/([0-9a-f-]{36})(?:\/|$)/i.exec(pathname)?.[1] ?? null;
}

function MessageBubble({ message }: { message: Pick<ChatMessageOut, "role" | "content"> & Partial<ChatMessageOut> }) {
  const mine = message.role === "user";
  return (
    <li className={cx("flex", mine ? "justify-end" : "justify-start")}>
      <div
        className={cx(
          "max-w-[92%] rounded-md border px-3 py-2 text-sm",
          mine ? "border-accent/30 bg-accent-subtle text-ink" : "border-line bg-surface text-ink",
        )}
      >
        <span className="sr-only">{mine ? "You said:" : "Assistant:"}</span>
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        {!mine && message.model && (
          <p className="mt-1.5 text-xs text-ink-3">
            {message.model}
            {message.output_tokens != null && ` · ${message.input_tokens ?? 0} in / ${message.output_tokens} out tokens`}
          </p>
        )}
        {message.truncated && <p className="mt-1 text-xs text-caution">The reply stopped at the length limit.</p>}
      </div>
    </li>
  );
}

/**
 * The assistant's chat box, shown on every page. Its context follows the page: on a household's pages it answers
 * about that household, elsewhere it is a general conversation. A reply that is streaming when the page
 * changes finishes in its own conversation before the panel switches.
 */
export function AssistantPanel({ householdId, onHide }: { householdId: string | null; onHide: () => void }) {
  const toast = useToast();
  const [context, setContext] = useState<string | null>(householdId);
  const providers = useApiQuery(() => endpoints.aiProviders(), []);
  const chats = useApiQuery(() => endpoints.listChats(context), [context]);
  const household = useApiQuery(() => endpoints.getHousehold(context as string), [context], Boolean(context));
  const [selected, setSelected] = useState<ChatOut | null>(null);
  const [messages, setMessages] = useState<ChatMessageOut[]>([]);
  const [loadingThread, setLoadingThread] = useState(false);
  const [threadError, setThreadError] = useState<unknown>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<{ question: string; answer: string } | null>(null);
  const [sendError, setSendError] = useState<unknown>(null);
  const [confirmDelete, setConfirmDelete] = useState<ChatOut | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const active = providers.data?.credentials.find((c) => c.is_active) ?? null;
  const activeLabel = providers.data?.providers.find((p) => p.provider === active?.provider)?.label ?? active?.provider;
  const noProvider = providers.data !== undefined && active === null;

  const startNew = () => {
    setSelected(null);
    setMessages([]);
    setSendError(null);
    setThreadError(null);
  };

  // Follow the page's household once no reply is in flight.
  useEffect(() => {
    if (pending || householdId === context) return;
    setContext(householdId);
    setSelected(null);
    setMessages([]);
    setSendError(null);
    setThreadError(null);
  }, [householdId, context, pending]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages, pending]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const open = async (chat: ChatOut) => {
    setSelected(chat);
    setSendError(null);
    setThreadError(null);
    setLoadingThread(true);
    try {
      setMessages((await endpoints.getChat(chat.id)).messages);
    } catch (e) {
      setThreadError(e);
    } finally {
      setLoadingThread(false);
    }
  };

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || pending) return;
    setSendError(null);
    setDraft("");
    setPending({ question, answer: "" });
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const chat = selected ?? (await endpoints.createChat(context));
      if (!selected) setSelected(chat);
      const done = await endpoints.sendChatMessage(
        chat.id,
        question,
        (delta) => setPending((p) => (p ? { ...p, answer: p.answer + delta } : p)),
        controller.signal,
      );
      setMessages((m) => [...m, done.user_message, done.assistant_message]);
      setSelected({ ...chat, title: done.title });
      void chats.reload();
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) setSendError(e);
      setDraft(question); // nothing was saved; let the advisor retry or edit
    } finally {
      abortRef.current = null;
      setPending(null);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send(draft);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(draft);
    }
  };

  const remove = async (chat: ChatOut) => {
    setConfirmDelete(null);
    try {
      await endpoints.deleteChat(chat.id);
      if (selected?.id === chat.id) startNew();
      void chats.reload();
    } catch (e) {
      const d = describeError(e);
      toast.error(d.message, d.requestId ? `Request ID: ${d.requestId}` : undefined);
    }
  };

  const options = chats.data ?? [];
  const empty = !selected && messages.length === 0 && !pending;
  const about = context ? (household.data?.name ?? "this household") : null;

  return (
    <section aria-label="Assistant" className="flex h-full min-h-0 flex-col bg-surface">
      <div className="space-y-2 border-b border-line bg-surface-muted px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-display text-base text-ink">Assistant</h2>
          <Button size="sm" variant="ghost" onClick={onHide} aria-label="Minimize assistant">
            Minimize
          </Button>
        </div>
        <p className="truncate text-xs text-ink-3" title={about ?? undefined}>
          {about ? `About ${about}` : "General · no client data"}
        </p>
        <div className="flex items-center gap-2">
          <label htmlFor="assistant-conversation" className="sr-only">
            Conversation
          </label>
          <select
            id="assistant-conversation"
            value={selected?.id ?? ""}
            disabled={!!pending || chats.loading}
            onChange={(e) => {
              const chat = options.find((c) => c.id === e.target.value);
              if (chat) void open(chat);
              else startNew();
            }}
            className="min-w-0 flex-1 rounded-sm border border-line-strong bg-surface px-2 py-1 text-sm text-ink"
          >
            <option value="">New conversation</option>
            {selected && !options.some((c) => c.id === selected.id) && (
              <option value={selected.id}>{selected.title}</option>
            )}
            {options.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          {selected && (
            <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(selected)} disabled={!!pending}>
              Delete
            </Button>
          )}
        </div>
        {chats.error != null && <ErrorState error={chats.error} onRetry={() => void chats.reload()} />}
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {providers.loading && !providers.data ? null : noProvider ? (
          <Notice tone="warning" title="Add an AI provider to use the assistant">
            The assistant answers with your own Anthropic or OpenAI key.{" "}
            <Link href="/settings/ai-providers" className="underline">
              Set one up in Settings → AI providers
            </Link>
            .
          </Notice>
        ) : active ? (
          <p className="text-xs text-ink-3">
            Answers use your {activeLabel} key{active.model ? ` · ${active.model}` : ""}.{" "}
            {context
              ? "It reads this household's approved terms, holdings, scenarios and latest results; it cannot change anything."
              : "Open a household to ask about a specific client."}
          </p>
        ) : null}

        {loadingThread ? (
          <LoadingBlock rows={3} label="Loading conversation…" />
        ) : threadError ? (
          <ErrorState error={threadError} onRetry={() => selected && void open(selected)} />
        ) : empty ? (
          <div className="space-y-2">
            <p className="text-sm text-ink-2">
              {context
                ? "Ask about this household's liquidity, contract terms or analysis results."
                : "Ask about OndhoDeck or liquidity concepts."}
            </p>
            <div className="flex flex-col items-stretch gap-2">
              {SUGGESTIONS[context ? "household" : "general"].map((s) => (
                <Button
                  key={s}
                  size="sm"
                  variant="secondary"
                  onClick={() => void send(s)}
                  disabled={noProvider}
                  className="justify-start text-left"
                >
                  {s}
                </Button>
              ))}
            </div>
          </div>
        ) : (
          <ol className="space-y-3" aria-label="Messages" aria-live="polite">
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} />
            ))}
            {pending && (
              <>
                <MessageBubble message={{ role: "user", content: pending.question }} />
                <MessageBubble message={{ role: "assistant", content: pending.answer || "Thinking…" }} />
              </>
            )}
          </ol>
        )}
        {sendError != null && (
          <Notice tone="danger" title="No reply">
            {describeError(sendError).message} Your message was not saved.
          </Notice>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="space-y-2 border-t border-line px-4 py-3">
        <label htmlFor="assistant-message" className="sr-only">
          Message
        </label>
        <textarea
          id="assistant-message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={MAX_CHARS}
          rows={3}
          disabled={noProvider}
          placeholder={context ? "Ask about this household…" : "Ask a question…"}
          className="w-full resize-none rounded-sm border border-line-strong bg-surface px-3 py-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-60"
        />
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-ink-3">Enter to send · Shift+Enter for a new line</p>
          {pending ? (
            <Button size="sm" variant="secondary" onClick={() => abortRef.current?.abort()}>
              Stop
            </Button>
          ) : (
            <Button type="submit" size="sm" variant="accent" disabled={noProvider || !draft.trim()}>
              Send
            </Button>
          )}
        </div>
        <p className="text-[11px] leading-snug text-ink-3">
          Answers are generated from OndhoDeck data and can be wrong; check figures on the analysis pages. Not
          investment advice.
        </p>
      </form>

      <Dialog
        open={confirmDelete !== null}
        title="Delete conversation?"
        onClose={() => setConfirmDelete(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmDelete(null)}>
              Cancel
            </Button>
            <Button variant="danger" onClick={() => confirmDelete && void remove(confirmDelete)}>
              Delete
            </Button>
          </>
        }
      >
        <p className="text-sm text-ink-2">&ldquo;{confirmDelete?.title}&rdquo; and its messages will be deleted.</p>
      </Dialog>
    </section>
  );
}
