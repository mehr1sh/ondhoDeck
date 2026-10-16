"use client";

import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "@/components/ui";

type ToastTone = "success" | "error" | "info";
interface ToastItem {
  id: number;
  tone: ToastTone;
  message: string;
  detail?: string;
}

interface ToastApi {
  success: (message: string, detail?: string) => void;
  error: (message: string, detail?: string) => void;
  info: (message: string, detail?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => setItems((all) => all.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (tone: ToastTone, message: string, detail?: string) => {
      const id = nextId.current++;
      setItems((all) => [...all.slice(-3), { id, tone, message, detail }]);
      setTimeout(() => dismiss(id), tone === "error" ? 8000 : 5000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      success: (m, d) => push("success", m, d),
      error: (m, d) => push("error", m, d),
      info: (m, d) => push("info", m, d),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-live="polite" role="status" className="pointer-events-none fixed inset-x-0 top-0 z-[60] flex flex-col items-center gap-2 p-4 sm:items-end">
        {items.map((t) => (
          <div
            key={t.id}
            className={cx(
              "pointer-events-auto w-full max-w-sm rounded-md border px-4 py-3 text-sm shadow-lg",
              t.tone === "success" && "border-lime-500 bg-white text-slate-900 border-l-4",
              t.tone === "error" && "border-red-300 bg-red-50 text-red-900",
              t.tone === "info" && "border-slate-300 bg-white text-slate-900",
            )}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-medium">{t.message}</p>
                {t.detail && <p className="mt-0.5 text-xs opacity-80">{t.detail}</p>}
              </div>
              <button type="button" aria-label="Dismiss notification" className="text-slate-500 hover:text-slate-800" onClick={() => dismiss(t.id)}>
                ✕
              </button>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const noop: ToastApi = { success: () => {}, error: () => {}, info: () => {} };

export function useToast(): ToastApi {
  return useContext(ToastContext) ?? noop;
}
