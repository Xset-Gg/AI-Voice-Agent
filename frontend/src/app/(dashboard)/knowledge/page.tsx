"use client";

import { AlertTriangle, BookOpen, FileText, MessageSquareText, RefreshCw, Search, ShieldCheck, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Loading, Modal, PageHeader, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtBytes, fmtRelative } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Chunk, KnowledgeDocument, Source } from "@/lib/types";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown,.csv,.html,.htm,.json";

function DocStatus({ doc }: { doc: KnowledgeDocument }) {
  if (doc.status === "ready") return doc.risk_flags.length
    ? <Badge tone="warn"><AlertTriangle className="size-3" /> Needs review</Badge>
    : <Badge tone="good">Ready</Badge>;
  if (doc.status === "failed") return <Badge tone="bad">Failed</Badge>;
  return <Badge tone="accent"><RefreshCw className="size-3 animate-spin" /> {doc.status === "pending" ? "Queued" : "Processing"}</Badge>;
}

function DocumentModal({ doc, onClose, onChanged }: { doc: KnowledgeDocument | null; onClose: () => void; onChanged: (d: KnowledgeDocument | null) => void }) {
  const { can } = useAuth();
  const chunks = useApi<Chunk[]>(doc ? `/knowledge/documents/${doc.id}/chunks` : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!doc) return null;

  const act = async (kind: "approve" | "reprocess" | "delete") => {
    setBusy(kind);
    setError(null);
    try {
      if (kind === "delete") {
        await api(`/knowledge/documents/${doc.id}`, { method: "DELETE" });
        onChanged(null);
        onClose();
      } else {
        onChanged(await api<KnowledgeDocument>(`/knowledge/documents/${doc.id}/${kind}`, { method: "POST" }));
        if (kind === "approve") chunks.reload();
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal open onClose={onClose} title={doc.title} wide
      footer={can("member") && (
        <>
          <Button variant="danger" loading={busy === "delete"} onClick={() => act("delete")}><Trash2 className="size-4" /> Delete</Button>
          <Button loading={busy === "reprocess"} onClick={() => act("reprocess")}><RefreshCw className="size-4" /> Reprocess</Button>
          {doc.risk_flags.length > 0 && can("admin") && (
            <Button variant="primary" loading={busy === "approve"} onClick={() => act("approve")}><ShieldCheck className="size-4" /> Approve content</Button>
          )}
        </>
      )}>
      <div className="space-y-4">
        {error && <ErrorBox message={error} />}
        {doc.error && <ErrorBox message={doc.error} />}
        {doc.risk_flags.length > 0 && (
          <div className="rounded-lg border border-warn/30 bg-warn-soft p-4 text-sm">
            <div className="mb-2 font-medium text-warn">Possible instructions hidden in this content</div>
            <p className="mb-2 text-ink-2">Flagged sections are excluded from calls until an admin approves them.</p>
            <ul className="space-y-1.5">
              {doc.risk_flags.map((f, i) => <li key={i} className="rounded bg-surface px-2 py-1 font-mono text-xs">{f.excerpt}</li>)}
            </ul>
          </div>
        )}
        <div className="text-xs text-ink-3">{doc.chunk_count} sections · {fmtBytes(doc.size_bytes)} · added {fmtRelative(doc.created_at)}</div>
        {chunks.loading ? <Loading /> : (
          <ol className="space-y-2">
            {chunks.data?.map((c) => (
              <li key={c.id} className="rounded-lg border border-line p-3 text-sm">
                <div className="mb-1 flex items-center gap-2 text-xs text-ink-3">
                  #{c.chunk_index + 1}{c.heading && ` · ${c.heading}`} · {c.token_count} tokens
                  {c.flagged && <Badge tone="warn">Flagged</Badge>}
                </div>
                <p className="whitespace-pre-wrap leading-relaxed text-ink-2">{c.text}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </Modal>
  );
}

function AddModal({ kind, onClose, onAdded }: { kind: "faq" | "text" | null; onClose: () => void; onAdded: (d: KnowledgeDocument) => void }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = kind === "faq" ? { question: a, answer: b } : { title: a, body: b };
      onAdded(await api<KnowledgeDocument>(kind === "faq" ? "/knowledge/faqs" : "/knowledge/texts", { body }));
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={!!kind} onClose={onClose} title={kind === "faq" ? "Add FAQ" : "Add text"} wide
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="kb-add" loading={busy}>Add</Button></>}>
      <form id="kb-add" onSubmit={submit} className="space-y-4">
        {error && <ErrorBox message={error} />}
        <Field label={kind === "faq" ? "Question" : "Title"}>
          <Input required minLength={kind === "faq" ? 3 : 1} value={a} onChange={(e) => setA(e.target.value)} placeholder={kind === "faq" ? "Do you offer weekend appointments?" : "Pricing 2026"} />
        </Field>
        <Field label={kind === "faq" ? "Answer" : "Content"}>
          <Textarea required rows={kind === "faq" ? 4 : 12} value={b} onChange={(e) => setB(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}

function SearchTester() {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<{ found: boolean; sources: Source[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setRes(await api("/knowledge/search", { body: { query: q, top_k: 5 } }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Test what the agent finds">
      <form onSubmit={run} className="flex gap-2 p-4">
        <Input placeholder="Ask a question a caller might ask…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Test query" />
        <Button type="submit" loading={busy}><Search className="size-4" /> Search</Button>
      </form>
      {error && <div className="px-4 pb-4"><ErrorBox message={error} /></div>}
      {res && (
        <div className="border-t border-line p-4">
          {!res.found ? <p className="text-sm text-warn">Nothing relevant found — the agent would say it doesn&apos;t know.</p> : (
            <ol className="space-y-2">
              {res.sources.map((s) => (
                <li key={s.chunk_id} className="rounded-lg border border-line p-3 text-sm">
                  <div className="mb-1 flex justify-between text-xs text-ink-3">
                    <span>{s.document_title}{s.heading && ` › ${s.heading}`}</span>
                    <span className="tabular-nums">score {s.score.toFixed(2)}</span>
                  </div>
                  <p className="line-clamp-4 text-ink-2">{s.text}</p>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </Card>
  );
}

export default function KnowledgePage() {
  const { can } = useAuth();
  const { data: docs, error, loading, reload, setData } = useApi<KnowledgeDocument[]>("/knowledge/documents");
  const [open, setOpen] = useState<KnowledgeDocument | null>(null);
  const [adding, setAdding] = useState<"faq" | "text" | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const processing = docs?.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const t = setInterval(reload, 3000);
    return () => clearInterval(t);
  }, [processing, reload]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploading(true);
    setUploadError(null);
    const errors: string[] = [];
    for (const file of Array.from(files)) {
      const form = new FormData();
      form.append("file", file);
      try {
        const doc = await api<KnowledgeDocument>("/knowledge/documents/upload", { form });
        setData((prev) => [doc, ...(prev ?? [])]);
      } catch (e) {
        errors.push(`${file.name}: ${(e as Error).message}`);
      }
    }
    if (errors.length) setUploadError(errors.join(" · "));
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  const replace = (d: KnowledgeDocument | null) => {
    if (!open) return;
    setData((prev) => (d ? (prev ?? []).map((x) => (x.id === d.id ? d : x)) : (prev ?? []).filter((x) => x.id !== open.id)));
    if (d) setOpen(d);
  };

  return (
    <>
      <PageHeader
        title="Knowledge Base"
        description="Documents and FAQs your agent uses to answer questions. It never makes up facts that aren't here."
        actions={can("member") && (
          <>
            <Button onClick={() => setAdding("faq")}><MessageSquareText className="size-4" /> Add FAQ</Button>
            <Button onClick={() => setAdding("text")}><FileText className="size-4" /> Add text</Button>
            <Button variant="primary" loading={uploading} onClick={() => fileRef.current?.click()}><Upload className="size-4" /> Upload files</Button>
            <input ref={fileRef} type="file" multiple accept={ACCEPT} className="hidden" onChange={(e) => upload(e.target.files)} />
          </>
        )}
      />
      <div className="space-y-4">
        {error && <ErrorBox message={error} onRetry={reload} />}
        {uploadError && <ErrorBox message={uploadError} />}
        <Card>
          {loading && !docs ? <Loading /> : !docs?.length ? (
            <Empty icon={<BookOpen className="size-6" />} title="Your knowledge base is empty"
              description="Upload PDFs, Word docs or text files, or add FAQs, so the agent can answer questions about your business." />
          ) : (
            <ul className="divide-y divide-line">
              {docs.map((d) => (
                <li key={d.id}>
                  <button onClick={() => setOpen(d)} className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 text-left hover:bg-surface-2">
                    <span className="text-ink-3">{d.source_type === "faq" ? <MessageSquareText className="size-4" /> : <FileText className="size-4" />}</span>
                    <span className="min-w-0 flex-1 truncate text-sm font-medium">{d.title}</span>
                    <span className="text-xs text-ink-3">{d.source_type === "file" ? d.filename : d.source_type.toUpperCase()}</span>
                    <span className="w-20 text-right text-xs tabular-nums text-ink-3">{d.chunk_count} sections</span>
                    <DocStatus doc={d} />
                    <span className="w-16 text-right text-xs text-ink-3">{fmtRelative(d.created_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <SearchTester />
      </div>
      <DocumentModal key={open?.id} doc={open} onClose={() => setOpen(null)} onChanged={replace} />
      <AddModal key={adding ?? "closed"} kind={adding} onClose={() => setAdding(null)} onAdded={(d) => setData((prev) => [d, ...(prev ?? [])])} />
    </>
  );
}
