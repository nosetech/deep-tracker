"use client";

import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastKind = "info" | "success" | "error";

type ToastAction = { label: string; onClick: () => void };

type ToastItem = {
  id: number;
  text: string;
  kind: ToastKind;
  action?: ToastAction;
};

type ShowToast = (text: string, kind?: ToastKind, action?: ToastAction) => void;

const ToastContext = createContext<ShowToast>(() => {});

export function useToast(): ShowToast {
  return useContext(ToastContext);
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);

  const close = useCallback((id: number) => {
    setToasts((ts) => ts.filter((t) => t.id !== id));
  }, []);

  const show = useCallback<ShowToast>(
    (text, kind = "info", action) => {
      const id = nextId.current++;
      setToasts((ts) => [...ts.slice(-2), { id, text, kind, action }]);
      setTimeout(() => close(id), action ? 6000 : 4000);
    },
    [close],
  );

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toast-region" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="toast" role="status">
            <span className={`toast-dot toast-dot-${t.kind}`} />
            <span className="toast-text">{t.text}</span>
            {t.action && (
              <button
                type="button"
                className="toast-action"
                onClick={() => {
                  close(t.id);
                  t.action!.onClick();
                }}
              >
                {t.action.label}
              </button>
            )}
            <button
              type="button"
              className="toast-close"
              aria-label="閉じる"
              onClick={() => close(t.id)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
