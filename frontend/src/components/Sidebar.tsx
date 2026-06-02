import { useEffect, useMemo, useState } from "react";
import type { Status } from "@/types";
import { api, type DocSummary } from "@/api/client";
import { GROUP_ORDER, getType } from "@/schema/types";
import type { DocType } from "@/schema/types";
import {
  IconDoc,
  IconChevronLeft,
  IconChevronRight,
  IconChevronDown,
  IconSearch,
  IconPlus,
  IconCheck,
  IconPause,
  IconX,
  IconCloud,
  IconTrash,
} from "./icons";

function StatusChip({ status }: { status: Status }) {
  if (status === "processing") return <span className="spinner" aria-label="processing" />;
  if (status === "done")
    return (
      <span className="status-chip done" aria-label="done">
        <IconCheck width={11} height={11} />
      </span>
    );
  if (status === "error")
    return (
      <span className="status-chip error" aria-label="error">
        <IconX width={11} height={11} />
      </span>
    );
  return (
    <span className="status-chip queued" aria-label="queued">
      <IconPause width={11} height={11} />
    </span>
  );
}

interface Props {
  docs: DocSummary[];
  activeId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onAdd: () => void;
}

export function Sidebar({ docs, activeId, collapsed, onToggleCollapse, onSelect, onDelete, onAdd }: Props) {
  const [query, setQuery] = useState("");
  const [serverDocs, setServerDocs] = useState<DocSummary[] | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<DocType>>(new Set());

  // ≥2 chars → debounced full-text search (content + filename); else local filename filter.
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) {
      setServerDocs(null);
      return;
    }
    const t = setTimeout(() => {
      api.search(q).then(setServerDocs).catch(() => setServerDocs([]));
    }, 250);
    return () => clearTimeout(t);
  }, [query]);

  const filtered = useMemo(() => {
    if (query.trim().length >= 2) return serverDocs ?? [];
    return docs.filter((d) => d.filename.toLowerCase().includes(query.toLowerCase()));
  }, [docs, query, serverDocs]);

  const grouped = useMemo(() => {
    const map = new Map<DocType, DocSummary[]>();
    for (const t of GROUP_ORDER) {
      const items = filtered.filter((d) => (d.type ?? "other") === t);
      if (items.length) map.set(t, items);
    }
    return map;
  }, [filtered]);

  if (collapsed) {
    const presentTypes = GROUP_ORDER.filter((t) => docs.some((d) => (d.type ?? "other") === t));
    return (
      <aside className="sidebar collapsed area-sidebar">
        <div className="rail">
          <button className="icon-btn" onClick={onToggleCollapse} aria-label="Expand sidebar">
            <IconChevronRight />
          </button>
          {presentTypes.map((t) => (
            <div key={t} className="rail-icon" title={getType(t).label}>
              <span style={{ fontSize: 16 }}>{getType(t).icon}</span>
            </div>
          ))}
          <button className="icon-btn rail-icon" onClick={onAdd} aria-label="Add documents">
            <IconPlus />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="sidebar area-sidebar">
      <div className="sidebar-head">
        <span className="section-label">File Explorer</span>
        <button className="icon-btn" onClick={onToggleCollapse} aria-label="Collapse sidebar">
          <IconChevronLeft />
        </button>
      </div>

      <div className="sidebar-search">
        <IconSearch width={15} height={15} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search documents…"
        />
      </div>

      <div className="doc-list">
        {docs.length === 0 ? (
          <div className="sidebar-empty">
            <IconCloud className="cloud" />
            <div className="t1">No documents yet</div>
            <div className="t2">Click + Add or drag files anywhere.</div>
          </div>
        ) : (
          [...grouped.entries()].map(([type, items]) => {
            const isCollapsed = collapsedGroups.has(type);
            return (
              <div key={type}>
                <button
                  className="group-head"
                  onClick={() => {
                    const next = new Set(collapsedGroups);
                    next.has(type) ? next.delete(type) : next.add(type);
                    setCollapsedGroups(next);
                  }}
                >
                  <IconChevronDown
                    width={14}
                    height={14}
                    className={`group-chev${isCollapsed ? " collapsed" : ""}`}
                  />
                  <span className="group-label">{getType(type).label}</span>
                  <span className="count-pill">{items.length}</span>
                </button>
                {!isCollapsed &&
                  items.map((d) => (
                    <div
                      key={d.id}
                      className={`doc-row${d.id === activeId ? " active" : ""}`}
                      onClick={() => onSelect(d.id)}
                    >
                      <IconDoc width={15} height={15} className="doc-icon" />
                      <span className="doc-name">{d.filename}</span>
                      {d.expiresInDays != null && d.expiresInDays <= 30 && (
                        <span
                          className={`expiry-dot${d.expiresInDays < 0 ? " expired" : ""}`}
                          title={
                            d.expiresInDays < 0
                              ? `Expiré il y a ${-d.expiresInDays} j`
                              : `Expire dans ${d.expiresInDays} j`
                          }
                        />
                      )}
                      <StatusChip status={d.status} />
                      <button
                        className="doc-del"
                        title="Delete document"
                        onClick={(e) => {
                          e.stopPropagation();
                          onDelete(d.id);
                        }}
                      >
                        <IconTrash width={14} height={14} />
                      </button>
                    </div>
                  ))}
              </div>
            );
          })
        )}
      </div>

      {docs.length > 0 && (
        <div className="status-legend">
          <span>✓ Done</span>
          <span>◐ Processing</span>
          <span>‖ Queued</span>
          <span>× Error</span>
        </div>
      )}

      <div className="sidebar-add">
        <button className="add-btn" onClick={onAdd}>
          <IconPlus width={15} height={15} />
          Add documents
        </button>
      </div>
    </aside>
  );
}
