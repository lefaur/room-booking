import { reactive } from "vue";

export interface Toast {
  id: number;
  kind: "success" | "error";
  text: string;
}

let next = 1;
export const toasts = reactive<Toast[]>([]);

export function notify(text: string, kind: Toast["kind"] = "success", ms = 4000): void {
  const toast = { id: next++, kind, text };
  toasts.push(toast);
  setTimeout(() => {
    const index = toasts.findIndex((t) => t.id === toast.id);
    if (index >= 0) toasts.splice(index, 1);
  }, ms);
}

export function notifyError(error: unknown): void {
  notify(error instanceof Error ? error.message : String(error), "error", 6000);
}
