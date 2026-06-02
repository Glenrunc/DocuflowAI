import { useState } from "react";
import type { DocData, FieldData } from "@/types";
import { CONF_BADGE, GROUP_ORDER, getType } from "@/schema/types";
import type { Confidence, DocType } from "@/schema/types";
import { IconPencil, IconChevronDown, IconSparkle, IconWarning } from "./icons";

const TOOLTIP: Record<Confidence, { title: string; body: string }> = {
  high: {
    title: "High confidence",
    body: "This value appears clearly and is consistent with the document layout.",
  },
  med: {
    title: "Review suggested",
    body: "We found this value but the surrounding context is ambiguous — please verify.",
  },
  low: {
    title: "Needs correction",
    body: "This region of the document is unclear or partially obscured. Manual correction recommended.",
  },
};

function ConfBadge({ conf }: { conf: Confidence }) {
  const [tip, setTip] = useState<{ x: number; y: number } | null>(null);
  const b = CONF_BADGE[conf];
  return (
    <>
      <span
        className="conf-badge"
        style={{ background: b.bg, color: b.fg }}
        onMouseEnter={(e) => setTip({ x: e.clientX, y: e.currentTarget.getBoundingClientRect().top })}
        onMouseLeave={() => setTip(null)}
      >
        <span className="conf-dot" style={{ background: b.fg }} />
        {b.label}
      </span>
      {tip && (
        <div className="conf-tip" style={{ left: tip.x, top: tip.y - 8 }}>
          <div className="tt-title">{TOOLTIP[conf].title}</div>
          <div>{TOOLTIP[conf].body}</div>
        </div>
      )}
    </>
  );
}

interface RowProps {
  field: FieldData;
  hot: boolean;
  onHot: (k: string | null) => void;
  onEdit: (key: string, value: string) => void;
  onCategory: (key: string, value: string) => void;
}

function CategoryRow({ field, onCategory }: { field: FieldData; onCategory: RowProps["onCategory"] }) {
  const [open, setOpen] = useState(false);
  const opt = field.options?.find((o) => o.value === field.value);
  return (
    <div className="fr-value" style={{ position: "relative", textAlign: "left", flex: 1 }}>
      {opt ? (
        <button
          className="cat-pill"
          style={{ background: opt.color + "1A", borderColor: opt.color + "4D", color: opt.color }}
          onClick={() => setOpen((o) => !o)}
        >
          <span className="cat-dot" style={{ background: opt.color }} />
          {opt.label}
          <IconChevronDown width={12} height={12} />
        </button>
      ) : (
        <button className="cat-pill uncategorized" onClick={() => setOpen((o) => !o)}>
          Uncategorized
          <IconChevronDown width={12} height={12} />
        </button>
      )}
      {open && (
        <div className="cat-dropdown">
          {field.options?.map((o) => (
            <button
              key={o.value}
              onClick={() => {
                onCategory(field.key, o.value);
                setOpen(false);
              }}
            >
              <span className="cat-dot" style={{ background: o.color }} />
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function FieldRow({ field, hot, onHot, onEdit, onCategory }: RowProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(field.value);

  if (field.kind === "category") {
    return (
      <div className="field-row" onMouseEnter={() => onHot(field.key)} onMouseLeave={() => onHot(null)}>
        <span className="fr-icon">{field.icon}</span>
        <span className="fr-label">{field.label}</span>
        <CategoryRow field={field} onCategory={onCategory} />
      </div>
    );
  }

  const empty = field.value === "—" || field.value === "";

  return (
    <div
      className={`field-row${hot ? " hot" : ""}`}
      onMouseEnter={() => onHot(field.key)}
      onMouseLeave={() => onHot(null)}
    >
      <span className="fr-icon">{field.icon}</span>
      <span className="fr-label">{field.label}</span>

      {editing ? (
        <>
          <input
            className="fr-input"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                onEdit(field.key, draft);
                setEditing(false);
              }
              if (e.key === "Escape") {
                setDraft(field.value);
                setEditing(false);
              }
            }}
          />
          <div className="fr-actions">
            <button
              className="btn-xs primary"
              onClick={() => {
                onEdit(field.key, draft);
                setEditing(false);
              }}
            >
              Save
            </button>
            <button
              className="btn-xs"
              onClick={() => {
                setDraft(field.value);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <span className={`fr-value${empty ? " empty" : ""}`}>{field.value}</span>
          <ConfBadge conf={field.confidence} />
          <button className="edit-btn" aria-label={`Edit ${field.label}`} onClick={() => setEditing(true)}>
            <IconPencil width={13} height={13} />
          </button>
        </>
      )}
    </div>
  );
}

interface Props {
  doc: DocData | null;
  showRegions: boolean;
  onToggleRegions: () => void;
  hot: string | null;
  onHot: (k: string | null) => void;
  onChangeType: (t: DocType) => void;
  onEditField: (key: string, value: string) => void;
  onSetCategory: (key: string, value: string) => void;
  onResolveDup: () => void;
}

export function FieldsPanel({
  doc,
  showRegions,
  onToggleRegions,
  hot,
  onHot,
  onChangeType,
  onEditField,
  onSetCategory,
  onResolveDup,
}: Props) {
  const [typeMenu, setTypeMenu] = useState(false);

  const head = (
    <div className="fields-head">
      <span className="section-label">Extracted Fields</span>
      <button
        className={`toggle${showRegions ? " on" : ""}`}
        onClick={onToggleRegions}
        aria-pressed={showRegions}
      >
        Show regions
        <span className="track">
          <span className="knob" />
        </span>
      </button>
    </div>
  );

  let body;
  if (!doc || doc.status === "queued" || doc.status === "error") {
    body = (
      <div className="fields-empty">
        <IconSparkle className="spark" />
        <div className="t1">Fields will appear here</div>
        <div>
          Drop a document on the left to instantly see its key fields, with confidence scores and
          editable values.
        </div>
      </div>
    );
  } else if (doc.status === "processing") {
    body = (
      <div className="fields-body">
        <div className="type-row">
          <span className="type-pill" style={{ background: "#f3f4f6", color: "var(--text-2)" }}>
            <span className="spinner" /> Detecting type…
          </span>
        </div>
        <div className="field-card">
          {Array.from({ length: 5 }).map((_, i) => (
            <div className="field-row" key={i}>
              <div className="skeleton-bar" style={{ width: "100%" }} />
            </div>
          ))}
        </div>
        <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 10 }}>
          Reading your document…
        </div>
      </div>
    );
  } else {
    const t = getType(doc.type ?? "other");
    body = (
      <div className="fields-body">
        <div className="type-row">
          <span className="type-pill" style={{ background: t.pill.bg, color: t.pill.fg }}>
            <span>{t.icon}</span>
            {t.label}
          </span>
          <button className="change-type" onClick={() => setTypeMenu((o) => !o)}>
            Change type ▾
          </button>
          {typeMenu && (
            <div className="popover">
              {GROUP_ORDER.map((tt) => (
                <button
                  key={tt}
                  onClick={() => {
                    onChangeType(tt);
                    setTypeMenu(false);
                  }}
                >
                  <span>{getType(tt).icon}</span>
                  {getType(tt).label}
                </button>
              ))}
            </div>
          )}
        </div>

        {doc.type === "other" && (
          <div className="other-notice">
            We didn't fully recognize this document type — fields are our best guess.
          </div>
        )}

        <div className="field-card">
          {doc.fields.map((f) => (
            <FieldRow
              key={f.key}
              field={f}
              hot={hot === f.key}
              onHot={onHot}
              onEdit={onEditField}
              onCategory={onSetCategory}
            />
          ))}
        </div>

        {doc.isDup && <DuplicateBanner doc={doc} onResolve={onResolveDup} />}
      </div>
    );
  }

  return (
    <div className="fields-panel area-fields">
      {head}
      {body}
    </div>
  );
}

function DuplicateBanner({ doc, onResolve }: { doc: DocData; onResolve: () => void }) {
  const val = (k: string) => doc.fields.find((f) => f.key === k)?.value ?? "—";
  let detail = "";
  if (doc.type === "invoice") detail = `${val("merchant")}, ${val("total")}, ${val("date")}`;
  else if (doc.type === "contract") detail = `${val("partyA")} / ${val("partyB")}`;
  else if (doc.type === "medical") detail = `${val("patient")}, ${val("date")}`;
  else detail = doc.fields.slice(0, 2).map((f) => f.value).join(", ");

  return (
    <div className="dup-banner">
      <IconWarning className="warn" width={18} height={18} />
      <div style={{ flex: 1 }}>
        <div className="dup-text">
          Possible duplicate. This looks like a document you already processed — {detail}.
        </div>
        <div className="dup-actions">
          <button className="dup-keep" onClick={onResolve}>
            Keep both
          </button>
          <button className="dup-mark" onClick={onResolve}>
            Mark as duplicate
          </button>
        </div>
      </div>
    </div>
  );
}
