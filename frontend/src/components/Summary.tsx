import { useEffect, useState } from "react";
import { getType, GROUP_ORDER } from "@/schema/types";
import type { DocType } from "@/schema/types";
import type { Status } from "@/types";
import { IconDoc, IconDownload } from "./icons";

interface Row {
  id: string;
  filename: string;
  type: DocType | null;
  keyLabel: string;
  keyField: string;
  conf: string;
  status: Status;
}
interface Deadline {
  id: string;
  filename: string;
  type: DocType | null;
  label: string;
  date: string;
  daysLeft: number;
  status: "expired" | "soon" | "ok";
}
interface SummaryData {
  totals: { total: number; done: number; pending: number };
  typeCounts: Partial<Record<DocType, number>>;
  dateRange: { label: string; weeks: number };
  rows: Row[];
  subsections: Partial<Record<DocType, Record<string, unknown>>>;
  deadlines: Deadline[];
}

const STATUS_COLOR: Record<Status, string> = {
  done: "var(--success)",
  processing: "var(--primary)",
  queued: "var(--text-3)",
  error: "var(--danger)",
};

function Donut({ counts }: { counts: Partial<Record<DocType, number>> }) {
  const present = GROUP_ORDER.filter((t) => (counts[t] ?? 0) > 0);
  const total = present.reduce((s, t) => s + (counts[t] ?? 0), 0);
  const r = 38;
  const c = 2 * Math.PI * r;
  let offset = 0;
  return (
    <div className="donut-card">
      <svg width={140} height={140} viewBox="0 0 140 140">
        <circle cx={70} cy={70} r={r} fill="none" stroke="#F3F4F6" strokeWidth={14} />
        {present.map((t) => {
          const frac = (counts[t] ?? 0) / total;
          const len = frac * c;
          const seg = (
            <circle
              key={t}
              cx={70}
              cy={70}
              r={r}
              fill="none"
              stroke={getType(t).donut}
              strokeWidth={14}
              strokeDasharray={`${len} ${c - len}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 70 70)"
            />
          );
          offset += len;
          return seg;
        })}
        <text x={70} y={68} textAnchor="middle" fontSize={14} fontWeight={600} fill="var(--text)">
          {total}
        </text>
        <text x={70} y={80} textAnchor="middle" fontSize={6.5} fill="var(--text-2)">
          DOCUMENTS
        </text>
      </svg>
      <div className="donut-legend">
        {present.map((t) => (
          <div className="legend-row" key={t}>
            <span className="swatch" style={{ background: getType(t).donut }} />
            {getType(t).label}
            <span className="pct">{Math.round(((counts[t] ?? 0) / total) * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SubCard({ type, data }: { type: DocType; data: Record<string, unknown> }) {
  const t = getType(type);
  const num = (k: string) => data[k] as number | undefined;
  const str = (k: string) => data[k] as string | undefined;

  let body;
  if (type === "invoice") {
    const breakdown = (data.categoryBreakdown ?? {}) as Record<string, number>;
    const opts = getType("invoice").fields.find((f) => f.kind === "category")?.options ?? [];
    const colorOf = (v: string) => opts.find((o) => o.value === v)?.color ?? "#9CA3AF";
    body = (
      <>
        <div className="sub-stat">
          Total spend <b>{num("totalSpend")?.toLocaleString() ?? 0} €</b>
        </div>
        <div className="sub-stat">
          Top merchant <b>{str("topMerchant") ?? "—"}</b> ({num("topMerchantCount") ?? 0})
        </div>
        <div className="cat-bar">
          {Object.entries(breakdown).map(([cat, pct]) => (
            <span key={cat} style={{ width: `${pct}%`, background: colorOf(cat) }} title={cat} />
          ))}
        </div>
        <div className="donut-legend">
          {Object.entries(breakdown).map(([cat, pct]) => (
            <div className="legend-row" key={cat}>
              <span className="swatch" style={{ background: colorOf(cat) }} />
              {opts.find((o) => o.value === cat)?.label ?? cat}
              <span className="pct">{pct}%</span>
            </div>
          ))}
        </div>
      </>
    );
  } else if (type === "contract") {
    body = (
      <>
        <div className="sub-stat">Active <b>{num("active") ?? 0}</b></div>
        <div className="sub-stat">Expired <b>{num("expired") ?? 0}</b></div>
        <div className="sub-stat">Avg value <b>{num("avgValue")?.toLocaleString() ?? "—"} €</b></div>
      </>
    );
  } else if (type === "medical") {
    body = (
      <>
        <div className="sub-stat">Distinct patients <b>{num("patients") ?? 0}</b></div>
        <div className="sub-stat">Distinct facilities <b>{num("facilities") ?? 0}</b></div>
      </>
    );
  } else if (type === "report") {
    body = (
      <>
        <div className="sub-stat">Distinct authors <b>{num("authors") ?? 0}</b></div>
        <div className="sub-stat">Date range <b>{str("dateRange") ?? "—"}</b></div>
      </>
    );
  } else if (type === "id") {
    body = (
      <>
        <div className="sub-stat">Distinct issuers <b>{num("issuers") ?? 0}</b></div>
        <div className="sub-stat">Soonest expiry <b>{str("soonestExpiry") ?? "—"}</b></div>
      </>
    );
  } else {
    body = <div className="sub-stat">Count <b>{num("count") ?? 0}</b></div>;
  }

  return (
    <div className="panel-card sub-card">
      <h3>
        <span>{t.icon}</span>
        {t.label}
      </h3>
      {body}
    </div>
  );
}

export function Summary({ onOpen }: { onOpen: (id: string) => void }) {
  const [data, setData] = useState<SummaryData | null>(null);

  useEffect(() => {
    fetch("/api/summary")
      .then((r) => r.json())
      .then(setData);
  }, []);

  if (!data) return <div className="summary">Loading…</div>;
  if (data.totals.done === 0)
    return (
      <div className="summary">
        <h1>Session summary</h1>
        <p className="sub">An overview of every document processed so far this session.</p>
        <p style={{ color: "var(--text-2)" }}>Process some documents to see your summary here.</p>
      </div>
    );

  const present = GROUP_ORDER.filter((t) => (data.typeCounts[t] ?? 0) > 0);

  return (
    <div className="area-summary summary">
      <h1>Session summary</h1>
      <p className="sub">An overview of every document processed so far this session.</p>

      <div className="stat-cards">
        <div className="stat-card">
          <div className="tile" style={{ background: "var(--primary)" }}>
            <IconDoc width={18} height={18} stroke="#fff" />
          </div>
          <div className="label">Total Documents</div>
          <div className="value">{data.totals.done} processed</div>
          <div className="csub">{data.totals.pending} pending or errored</div>
        </div>
        <div className="stat-card">
          <div className="tile" style={{ background: "#14B8A6" }}>
            <IconDoc width={18} height={18} stroke="#fff" />
          </div>
          <div className="label">Types Detected</div>
          <div className="value">{present.length} types</div>
          <div className="csub">{present.map((t) => getType(t).label).join(", ")}</div>
        </div>
        <div className="stat-card">
          <div className="tile" style={{ background: "var(--warning)" }}>
            <IconDoc width={18} height={18} stroke="#fff" />
          </div>
          <div className="label">Date Range</div>
          <div className="value" style={{ fontSize: 20 }}>{data.dateRange.label}</div>
          <div className="csub">Across {data.dateRange.weeks} weeks</div>
        </div>
      </div>

      <div className="donut-row">
        <div className="panel-card">
          <Donut counts={data.typeCounts} />
        </div>
        <div className="panel-card">
          <div className="table-head">
            <span className="section-label">All documents</span>
            <a
              className="btn btn-ghost"
              href="/api/export.csv?profile=flat"
              style={{ textDecoration: "none" }}
            >
              <IconDownload width={15} height={15} />
              Export all CSV
            </a>
          </div>
          <table className="sum-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Key field</th>
                <th>Conf.</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((row) => (
                <tr key={row.id} onClick={() => onOpen(row.id)}>
                  <td>{row.filename}</td>
                  <td>
                    {row.type && (
                      <span
                        className="type-pill"
                        style={{
                          background: getType(row.type).pill.bg,
                          color: getType(row.type).pill.fg,
                        }}
                      >
                        <span>{getType(row.type).icon}</span>
                        {getType(row.type).label}
                      </span>
                    )}
                  </td>
                  <td>{row.keyField || "—"}</td>
                  <td>{row.conf}</td>
                  <td>
                    <span className="status-inline">
                      <span className="dot" style={{ background: STATUS_COLOR[row.status] }} />
                      {row.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {data.deadlines.some((d) => d.status !== "ok") && (
        <div className="panel-card deadlines-card">
          <span className="section-label">⏰ Échéances</span>
          <ul className="deadline-list">
            {data.deadlines
              .filter((d) => d.status !== "ok")
              .map((d) => (
                <li
                  key={d.id}
                  className={`deadline-row ${d.status}`}
                  onClick={() => onOpen(d.id)}
                >
                  <span className="dl-name">{d.filename}</span>
                  <span className="dl-label">{d.label}</span>
                  <span className="dl-when">
                    {d.daysLeft < 0
                      ? `Expiré (${d.date})`
                      : `Dans ${d.daysLeft} j (${d.date})`}
                  </span>
                </li>
              ))}
          </ul>
        </div>
      )}

      <div className="subsections">
        {present.map((t) => (
          <SubCard key={t} type={t} data={data.subsections[t] ?? {}} />
        ))}
      </div>
    </div>
  );
}
