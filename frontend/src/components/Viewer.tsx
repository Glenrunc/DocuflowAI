import { useState } from "react";
import type { DocData } from "@/types";
import { BBOX_PALETTE, getType } from "@/schema/types";
import { IconCloud, IconDoc, IconTrash } from "./icons";

function PipelineBar({ stages }: { stages: NonNullable<DocData["stages"]> }) {
  if (!stages.length) return null;
  const total = stages.reduce((s, x) => s + x.ms, 0);
  return (
    <div className="pipeline">
      {stages.map((s, i) => (
        <span key={s.key} className="pl-step">
          <span className="pl-dot" />
          <span className="pl-label">{s.label}</span>
          <span className="pl-ms">{s.ms}ms</span>
          {i < stages.length - 1 && <span className="pl-arrow">→</span>}
        </span>
      ))}
      <span className="pl-total">{(total / 1000).toFixed(1)}s total</span>
    </div>
  );
}

function TypePill({ type }: { type: DocData["type"] }) {
  if (!type) return null;
  const t = getType(type);
  return (
    <span className="type-pill" style={{ background: t.pill.bg, color: t.pill.fg }}>
      <span>{t.icon}</span>
      {t.label}
    </span>
  );
}

export function ViewerEmpty({ onFiles }: { onFiles: (f: FileList) => void }) {
  const [drag, setDrag] = useState(false);
  return (
    <div className="viewer area-viewer">
      <div className="viewer-center">
        <label
          className={`dropzone${drag ? " drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            if (e.dataTransfer.files.length) onFiles(e.dataTransfer.files);
          }}
        >
          <IconCloud className="cloud" />
          <h2>Drop a document to get started</h2>
          <p>
            We'll extract the key fields in seconds. Drop one or more documents of any type — or
            click to browse.
          </p>
          <div className="format-hint">PDF · JPG · PNG · HEIC</div>
          <input
            type="file"
            multiple
            hidden
            accept=".pdf,.jpg,.jpeg,.png,.heic"
            onChange={(e) => e.target.files && onFiles(e.target.files)}
          />
        </label>
      </div>
    </div>
  );
}

function GhostPaper({ blur }: { blur?: boolean }) {
  return (
    <div className={`paper${blur ? " processing-blur" : ""}`}>
      <div className="ghost" style={{ width: "55%", height: 16 }} />
      <div className="ghost" style={{ width: "35%" }} />
      <div style={{ height: 18 }} />
      {Array.from({ length: 8 }).map((_, i) => (
        <div key={i} className="ghost" style={{ width: `${90 - (i % 3) * 18}%` }} />
      ))}
    </div>
  );
}

export function ViewerProcessing() {
  return (
    <div className="viewer area-viewer">
      <div className="paper-wrap">
        <div style={{ position: "relative", width: "100%", maxWidth: 640 }}>
          <GhostPaper blur />
          <div className="processing-overlay">
            <div className="big-spinner" />
            <div className="t1">Reading your document…</div>
            <div className="t2">Extracting fields and bounding regions</div>
          </div>
        </div>
      </div>
    </div>
  );
}

interface LoadedProps {
  doc: DocData;
  showRegions: boolean;
  hot: string | null;
  onHot: (key: string | null) => void;
  onDelete: (id: string) => void;
}

export function ViewerLoaded({ doc, showRegions, hot, onHot, onDelete }: LoadedProps) {
  const boxed = doc.fields.filter((f) => f.bbox);
  const fileUrl = `/api/documents/${doc.id}/file`;
  const isImage = doc.mime.startsWith("image/");
  const isPdf = doc.mime === "application/pdf";
  return (
    <div className="viewer area-viewer">
      <div className="viewer-head">
        <IconDoc width={16} height={16} style={{ color: "var(--text-3)" }} />
        <span className="vh-name">{doc.filename}</span>
        <TypePill type={doc.type} />
        <span className="vh-meta">
          Page 1/{doc.pageCount}
          {doc.readMs ? ` · Read in ${(doc.readMs / 1000).toFixed(1)}s` : ""}
        </span>
        <button
          className="vh-delete"
          title="Delete document"
          onClick={() => onDelete(doc.id)}
        >
          <IconTrash width={15} height={15} />
        </button>
      </div>

      {doc.stages?.length ? <PipelineBar stages={doc.stages} /> : null}

      <div className="paper-wrap">
        <div className="doc-canvas">
          {isImage ? (
            <img className="doc-img" src={fileUrl} alt={doc.filename} />
          ) : isPdf ? (
            <img className="doc-img" src={`/api/documents/${doc.id}/preview`} alt={doc.filename} />
          ) : (
            <GhostPaper />
          )}
          <div className="bbox-layer">
            {boxed.map((f, i) => {
              const [x, y, w, h] = f.bbox!;
              const color = BBOX_PALETTE[i % BBOX_PALETTE.length];
              const isHot = hot === f.key;
              const cls = `bbox${isHot ? " hot" : showRegions ? " visible" : ""}`;
              return (
                <div
                  key={f.key}
                  className={cls}
                  style={{
                    color,
                    left: `${x}%`,
                    top: `${y}%`,
                    width: `${w}%`,
                    height: `${h}%`,
                  }}
                  onMouseEnter={() => onHot(f.key)}
                  onMouseLeave={() => onHot(null)}
                >
                  {isHot && (
                    <span className="bbox-label">
                      <span>{f.label}</span>
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
