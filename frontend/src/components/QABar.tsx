import { useState } from "react";
import type { QAEntry } from "@/types";
import { IconSparkle, IconSend } from "./icons";

export type QaScope = "doc" | "all";

interface Streaming {
  question: string;
  thinking: string;
  answer: string;
}

interface Props {
  docHistory: QAEntry[];
  allHistory: QAEntry[];
  streaming: Streaming | null;
  loading: boolean;
  suggested?: string[];
  onAsk: (question: string, scope: QaScope) => void;
}

function Thinking({ text, live }: { text: string; live?: boolean }) {
  if (!text) return null;
  return (
    <details className="qa-think" open={live}>
      <summary>{live ? "Réflexion…" : "Réflexion"}</summary>
      <div className="qa-think-body">{text}</div>
    </details>
  );
}

export function QABar({ docHistory, allHistory, streaming, loading, suggested, onAsk }: Props) {
  const [value, setValue] = useState("");
  const [scope, setScope] = useState<QaScope>("doc");

  const history = scope === "all" ? allHistory : docHistory;
  const showStream = scope === "all" && streaming;
  const showChips = scope === "doc" && history.length === 0 && (suggested?.length ?? 0) > 0;

  const submit = () => {
    const q = value.trim();
    if (!q) return;
    onAsk(q, scope);
    setValue("");
  };

  return (
    <div className="qa-bar area-qa">
      {(history.length > 0 || showStream || (loading && scope === "doc")) && (
        <div className="qa-history">
          {history.map((e, i) => (
            <div key={i} style={{ display: "contents" }}>
              <div className="qa-q">{e.question}</div>
              <div className="qa-a">
                {e.thinking && <Thinking text={e.thinking} />}
                {e.answer}
                {e.citation && <div className="qa-cite">{e.citation}</div>}
              </div>
            </div>
          ))}
          {showStream && (
            <>
              <div className="qa-q">{streaming!.question}</div>
              <div className="qa-a">
                <Thinking text={streaming!.thinking} live />
                {streaming!.answer || (!streaming!.thinking && "Looking…")}
              </div>
            </>
          )}
          {loading && scope === "doc" && <div className="qa-a">Looking…</div>}
        </div>
      )}

      {showChips && (
        <div className="qa-chips">
          {suggested!.map((s) => (
            <button key={s} onClick={() => onAsk(s, "doc")}>
              {s}
            </button>
          ))}
        </div>
      )}

      <div className="qa-scope">
        <button className={scope === "doc" ? "active" : ""} onClick={() => setScope("doc")}>
          📄 Ce document
        </button>
        <button className={scope === "all" ? "active" : ""} onClick={() => setScope("all")}>
          🗂 Tous les documents
        </button>
      </div>

      <div className="qa-input">
        <IconSparkle className="lead" width={16} height={16} />
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={
            scope === "all"
              ? "Ask about all documents…"
              : "Ask a question about this document…"
          }
        />
        <button className="qa-send" onClick={submit} disabled={!value.trim()} aria-label="Send">
          <IconSend width={16} height={16} />
        </button>
      </div>
    </div>
  );
}
