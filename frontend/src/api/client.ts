import type { DocData, QAEntry, Status } from "@/types";
import type { DocType } from "@/schema/types";

export interface DocSummary {
  id: string;
  filename: string;
  type: DocType | null;
  status: Status;
  isDup: boolean;
  pageCount: number;
  expiresInDays?: number | null;
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  list: () => fetch("/api/documents").then(json<DocSummary[]>),

  search: (q: string) =>
    fetch(`/api/documents/search?q=${encodeURIComponent(q)}`).then(json<DocSummary[]>),

  get: (id: string) => fetch(`/api/documents/${id}`).then(json<DocData>),

  status: (id: string) =>
    fetch(`/api/documents/${id}/status`).then(json<{ status: Status; errorMsg: string | null }>),

  upload: (files: FileList) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return fetch("/api/documents", { method: "POST", body: fd }).then(json<DocSummary[]>);
  },

  changeType: (id: string, type: DocType) =>
    fetch(`/api/documents/${id}/type`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type }),
    }).then(json<DocData>),

  editField: (id: string, key: string, value: string) =>
    fetch(`/api/documents/${id}/fields/${encodeURIComponent(key)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }).then(json<DocData>),

  setCategory: (id: string, value: string) =>
    fetch(`/api/documents/${id}/category`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    }).then(json<DocData>),

  resolveDuplicate: (id: string, action: "keep_both" | "mark_duplicate") =>
    fetch(`/api/documents/${id}/duplicate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    }).then(json<DocSummary>),

  ask: (id: string, question: string) =>
    fetch(`/api/documents/${id}/qa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    }).then(json<QAEntry>),

  summary: () => fetch("/api/summary").then(json),

  askAllStream: async (
    question: string,
    history: { question: string; answer: string }[],
    cb: {
      onThinking: (delta: string) => void;
      onAnswer: (delta: string) => void;
      onDone: (citation: string | null) => void;
    },
  ) => {
    const res = await fetch("/api/qa", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    if (!res.ok || !res.body) throw new Error(`QA failed (${res.status})`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl: number;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        const msg = JSON.parse(line) as { type: string; text?: string; citation?: string | null };
        if (msg.type === "thinking") cb.onThinking(msg.text ?? "");
        else if (msg.type === "tool") cb.onThinking("\n" + (msg.text ?? "") + "\n");
        else if (msg.type === "answer") cb.onAnswer(msg.text ?? "");
        else if (msg.type === "done") cb.onDone(msg.citation ?? null);
      }
    }
  },

  del: (id: string) =>
    fetch(`/api/documents/${id}`, { method: "DELETE" }).then((res) => {
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
    }),
};
