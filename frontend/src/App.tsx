import { useCallback, useEffect, useState } from "react";
import type { DocData, QAEntry } from "@/types";
import { getType, type DocType } from "@/schema/types";
import { api, type DocSummary } from "@/api/client";
import { Topbar, type Tab } from "@/components/Topbar";
import { Sidebar } from "@/components/Sidebar";
import { ViewerEmpty, ViewerProcessing, ViewerLoaded } from "@/components/Viewer";
import { FieldsPanel } from "@/components/FieldsPanel";
import { QABar } from "@/components/QABar";
import { Summary } from "@/components/Summary";

export default function App() {
  const [summaries, setSummaries] = useState<DocSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [activeDoc, setActiveDoc] = useState<DocData | null>(null);
  const [tab, setTab] = useState<Tab>("document");
  const [collapsed, setCollapsed] = useState(false);
  const [showRegions, setShowRegions] = useState(false);
  const [hot, setHot] = useState<string | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [globalQa, setGlobalQa] = useState<QAEntry[]>([]);
  const [streaming, setStreaming] = useState<
    { question: string; thinking: string; answer: string } | null
  >(null);

  const refreshList = useCallback(() => api.list().then(setSummaries), []);

  useEffect(() => {
    refreshList();
  }, [refreshList]);

  const select = useCallback((id: string) => {
    setActiveId(id);
    setHot(null);
    api.get(id).then(setActiveDoc);
  }, []);

  // Auto-select first document once the list loads.
  useEffect(() => {
    if (!activeId && summaries.length) select(summaries[0].id);
  }, [summaries, activeId, select]);

  // Poll while any document is still queued/processing.
  useEffect(() => {
    const pending = summaries.some((s) => s.status === "queued" || s.status === "processing");
    if (!pending) return;
    const t = setInterval(refreshList, 1500);
    return () => clearInterval(t);
  }, [summaries, refreshList]);

  // Refetch the active document's detail when its status changes (e.g. processing -> done).
  useEffect(() => {
    if (!activeId) return;
    const s = summaries.find((x) => x.id === activeId);
    if (s && activeDoc && s.status !== activeDoc.status) {
      api.get(activeId).then(setActiveDoc);
    }
  }, [summaries, activeId, activeDoc]);

  const canExport = summaries.some((s) => s.status === "done");

  const upload = (files: FileList) => {
    if (!files.length) return;
    api.upload(files).then((created) => {
      refreshList();
      if (created[0]) select(created[0].id);
    });
  };

  const pickFiles = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = ".pdf,.jpg,.jpeg,.png,.heic";
    input.onchange = () => input.files && upload(input.files);
    input.click();
  };

  const applyDoc = (d: DocData) => {
    setActiveDoc(d);
    refreshList();
  };

  const onDelete = (id: string) => {
    api.del(id).then(() => {
      if (id === activeId) {
        setActiveId(null);
        setActiveDoc(null);
        setHot(null);
      }
      refreshList();
    });
  };

  if (tab === "summary") {
    return (
      <div className="app-shell summary-mode">
        <Topbar
          tab={tab}
          onTab={setTab}
          canExport={canExport}
          onExport={() => window.open("/api/export.csv?profile=flat", "_blank")}
          onNew={() => setTab("document")}
        />
        <Summary onOpen={(id) => { setTab("document"); select(id); }} />
      </div>
    );
  }

  let viewer;
  if (!activeDoc || activeDoc.status === "queued" || activeDoc.status === "error") {
    viewer = <ViewerEmpty onFiles={upload} />;
  } else if (activeDoc.status === "processing") {
    viewer = <ViewerProcessing />;
  } else {
    viewer = (
      <ViewerLoaded
        doc={activeDoc}
        showRegions={showRegions}
        hot={hot}
        onHot={setHot}
        onDelete={onDelete}
      />
    );
  }

  return (
    <div className="app-shell" style={{ ["--sidebar-w" as string]: collapsed ? "44px" : "240px" }}>
      <Topbar
        tab={tab}
        onTab={setTab}
        canExport={canExport}
        onExport={() => window.open("/api/export.csv?profile=flat", "_blank")}
        onNew={pickFiles}
      />
      <Sidebar
        docs={summaries}
        activeId={activeId}
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((c) => !c)}
        onSelect={select}
        onDelete={onDelete}
        onAdd={pickFiles}
      />
      {viewer}
      <FieldsPanel
        doc={activeDoc}
        showRegions={showRegions}
        onToggleRegions={() => setShowRegions((s) => !s)}
        hot={hot}
        onHot={setHot}
        onChangeType={(t: DocType) => activeId && api.changeType(activeId, t).then(applyDoc)}
        onEditField={(key, value) => activeId && api.editField(activeId, key, value).then(applyDoc)}
        onSetCategory={(_key, value) => activeId && api.setCategory(activeId, value).then(applyDoc)}
        onResolveDup={() =>
          activeId &&
          api.resolveDuplicate(activeId, "keep_both").then(() => {
            setActiveDoc((d) => (d ? { ...d, isDup: false } : d));
            refreshList();
          })
        }
      />
      <QABar
        docHistory={activeDoc?.qa ?? []}
        allHistory={globalQa}
        streaming={streaming}
        loading={qaLoading}
        suggested={activeDoc?.type ? getType(activeDoc.type).suggested : undefined}
        onAsk={(q, scope) => {
          if (scope === "all") {
            setQaLoading(true);
            setStreaming({ question: q, thinking: "", answer: "" });
            let th = "";
            let an = "";
            api
              .askAllStream(q, {
                onThinking: (d) => {
                  th += d;
                  setStreaming((s) => (s ? { ...s, thinking: th } : s));
                },
                onAnswer: (d) => {
                  an += d;
                  setStreaming((s) => (s ? { ...s, answer: an } : s));
                },
                onDone: (citation) => {
                  setGlobalQa((h) => [
                    ...h,
                    { question: q, answer: an, citation: citation ?? undefined, thinking: th || undefined },
                  ]);
                  setStreaming(null);
                  setQaLoading(false);
                },
              })
              .catch(() => {
                setStreaming(null);
                setQaLoading(false);
              });
            return;
          }
          if (!activeId) return;
          setQaLoading(true);
          api
            .ask(activeId, q)
            .then((entry) =>
              setActiveDoc((d) => (d ? { ...d, qa: [...(d.qa ?? []), entry] } : d)),
            )
            .finally(() => setQaLoading(false));
        }}
      />
    </div>
  );
}
