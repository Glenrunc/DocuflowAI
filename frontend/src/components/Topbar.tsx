import { IconDoc, IconPlus, IconDownload } from "./icons";

export type Tab = "document" | "summary";

interface Props {
  tab: Tab;
  onTab: (t: Tab) => void;
  canExport: boolean;
  onExport: () => void;
  onNew: () => void;
}

export function Topbar({ tab, onTab, canExport, onExport, onNew }: Props) {
  return (
    <div className="topbar area-topbar">
      <div className="brand">
        <span className="brand-mark">
          <IconDoc width={16} height={16} stroke="#fff" />
        </span>
        <span className="brand-word">
          DocuFlow <span className="ai">AI</span>
        </span>
      </div>

      <div className="tab-switch" role="tablist">
        <button
          role="tab"
          className={tab === "document" ? "active" : ""}
          onClick={() => onTab("document")}
        >
          Document
        </button>
        <button
          role="tab"
          className={tab === "summary" ? "active" : ""}
          onClick={() => onTab("summary")}
        >
          Summary
        </button>
      </div>

      <div className="spacer" />

      {canExport && (
        <button className="btn btn-success" onClick={onExport}>
          <IconDownload width={15} height={15} />
          Export CSV
        </button>
      )}
      <button className="btn btn-ghost" onClick={onNew}>
        <IconPlus width={15} height={15} />
        New
      </button>
    </div>
  );
}
