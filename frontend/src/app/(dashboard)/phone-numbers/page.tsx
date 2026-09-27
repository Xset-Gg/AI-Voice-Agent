"use client";

import { Phone, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select } from "@/components/ui";
import { useAgents } from "@/lib/agents";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtPhone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { PhoneNumber, ProviderNumber } from "@/lib/types";

function ClaimModal({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: (n: PhoneNumber) => void }) {
  const provider = useApi<ProviderNumber[]>(open ? "/phone-numbers/provider" : null);
  const agents = useAgents();
  const [e164, setE164] = useState("");
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const available = provider.data?.filter((n) => !n.claimed) ?? [];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onAdded(await api<PhoneNumber>("/phone-numbers", {
        body: { e164: e164 || available[0]?.e164, friendly_name: name, agent_id: agentId || agents.data?.[0]?.id || null },
      }));
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Connect a Twilio number"
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="claim" loading={busy} disabled={!available.length}>Connect</Button></>}>
      <form id="claim" onSubmit={submit} className="space-y-4">
        {error && <ErrorBox message={error} />}
        {provider.error && <ErrorBox message={provider.error} />}
        {provider.loading ? <Loading /> : provider.data && !available.length ? (
          <p className="rounded-lg bg-surface-2 p-3 text-sm text-ink-2">No unclaimed numbers in your Twilio account. Buy one in the Twilio console, then come back.</p>
        ) : (
          <>
            <Field label="Twilio number">
              <Select value={e164} onChange={(e) => setE164(e.target.value)}>
                {available.map((n) => <option key={n.sid} value={n.e164}>{fmtPhone(n.e164)} · {n.friendly_name}</option>)}
              </Select>
            </Field>
            <Field label="Label" hint="Optional, e.g. “Main line”."><Input maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Answered by">
              <Select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                {agents.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </Select>
            </Field>
            <p className="text-xs text-ink-3">We&apos;ll point this number&apos;s voice webhook at the platform automatically.</p>
          </>
        )}
      </form>
    </Modal>
  );
}

export default function PhoneNumbersPage() {
  const { can } = useAuth();
  const { data, error, loading, reload, setData } = useApi<PhoneNumber[]>("/phone-numbers");
  const agents = useAgents();
  const [claiming, setClaiming] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<PhoneNumber | null>(null);

  const assign = async (n: PhoneNumber, agent_id: string) => {
    setActionError(null);
    try {
      const updated = await api<PhoneNumber>(`/phone-numbers/${n.id}`, { method: "PATCH", body: { agent_id: agent_id || null } });
      setData((prev) => (prev ?? []).map((x) => (x.id === n.id ? updated : x)));
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const remove = async () => {
    if (!removing) return;
    setActionError(null);
    try {
      await api(`/phone-numbers/${removing.id}`, { method: "DELETE" });
      setData((prev) => (prev ?? []).filter((x) => x.id !== removing.id));
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setRemoving(null);
    }
  };

  return (
    <>
      <PageHeader
        title="Phone Numbers"
        description="Numbers your customers call. Each one is answered by an AI agent."
        actions={can("admin") && <Button variant="primary" onClick={() => setClaiming(true)}><Plus className="size-4" /> Connect number</Button>}
      />
      {error && <ErrorBox message={error} onRetry={reload} />}
      {actionError && <div className="mb-4"><ErrorBox message={actionError} /></div>}
      <Card>
        {loading && !data ? <Loading /> : !data?.length ? (
          <Empty icon={<Phone className="size-6" />} title="No numbers connected" description="Connect a number from your Twilio account to start taking calls." />
        ) : (
          <ul className="divide-y divide-line">
            {data.map((n) => (
              <li key={n.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="font-medium tabular-nums">{fmtPhone(n.e164)}</div>
                  <div className="text-xs text-ink-3">{n.friendly_name || "—"} · {n.provider}</div>
                </div>
                {!n.agent_id && <Badge tone="warn">Not answering</Badge>}
                <Select className="w-44" value={n.agent_id ?? ""} disabled={!can("admin")} onChange={(e) => assign(n, e.target.value)} aria-label="Agent">
                  <option value="">No agent</option>
                  {agents.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
                {can("admin") && (
                  <Button size="sm" variant="ghost" onClick={() => setRemoving(n)} aria-label={`Remove ${n.e164}`}><Trash2 className="size-4" /></Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <ClaimModal open={claiming} onClose={() => setClaiming(false)} onAdded={(n) => setData((prev) => [...(prev ?? []), n])} />
      <Modal open={!!removing} onClose={() => setRemoving(null)} title="Remove number?"
        footer={<><Button onClick={() => setRemoving(null)}>Cancel</Button><Button variant="danger" onClick={remove}>Remove</Button></>}>
        <p className="text-sm text-ink-2">Calls to {removing && fmtPhone(removing.e164)} will no longer be answered by the platform. The number stays in your Twilio account.</p>
      </Modal>
    </>
  );
}
