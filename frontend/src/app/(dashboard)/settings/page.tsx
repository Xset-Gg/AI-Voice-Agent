"use client";

import { Plus, ScrollText, Users } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select, Tabs } from "@/components/ui";
import { timezoneOptions } from "@/lib/agents";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDateTime, humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { AuditEntry, Organization, Role, User } from "@/lib/types";

type View = "organization" | "team" | "audit";
const ROLES: Role[] = ["viewer", "member", "admin", "owner"];

function OrganizationView() {
  const { me, can, refresh } = useAuth();
  const [name, setName] = useState(me!.organization.name);
  const [tz, setTz] = useState(me!.organization.timezone);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const owner = can("owner");

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api<Organization>("/organization", { method: "PATCH", body: { name, timezone: tz } });
      await refresh();
      setSaved(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Business">
      <form onSubmit={save} className="grid max-w-2xl gap-4 p-5 sm:grid-cols-2">
        {error && <div className="sm:col-span-2"><ErrorBox message={error} /></div>}
        <Field label="Business name"><Input required minLength={2} disabled={!owner} value={name} onChange={(e) => { setName(e.target.value); setSaved(false); }} /></Field>
        <Field label="Timezone">
          <Select value={tz} disabled={!owner} onChange={(e) => { setTz(e.target.value); setSaved(false); }}>
            {timezoneOptions(tz).map((t) => <option key={t}>{t}</option>)}
          </Select>
        </Field>
        <Field label="Account ID" hint="Share with support if you need help."><Input readOnly value={me!.organization.slug} /></Field>
        {owner && <div className="flex items-end"><Button variant="primary" type="submit" loading={busy}>{saved ? "Saved" : "Save"}</Button></div>}
      </form>
    </Card>
  );
}

function TeamView() {
  const { me, can } = useAuth();
  const { data: users, error, loading, reload, setData } = useApi<User[]>("/users");
  const [inviting, setInviting] = useState(false);
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "member" as Role });
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const invite = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      const u = await api<User>("/users", { body: form });
      setData((prev) => [...(prev ?? []), u]);
      setInviting(false);
      setForm({ full_name: "", email: "", password: "", role: "member" });
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const update = async (u: User, body: Partial<Pick<User, "role" | "is_active">>) => {
    setActionError(null);
    try {
      const updated = await api<User>(`/users/${u.id}`, { method: "PATCH", body });
      setData((prev) => (prev ?? []).map((x) => (x.id === u.id ? updated : x)));
    } catch (e) {
      setActionError((e as Error).message);
    }
  };

  const assignable = ROLES.filter((r) => r !== "owner" || can("owner"));

  return (
    <>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {actionError && <div className="mb-4"><ErrorBox message={actionError} /></div>}
      <Card title="Team members" action={<Button size="sm" variant="primary" onClick={() => setInviting(true)}><Plus className="size-3.5" /> Add member</Button>}>
        {loading && !users ? <Loading /> : !users?.length ? <Empty icon={<Users className="size-6" />} title="No team members" /> : (
          <ul className="divide-y divide-line">
            {users.map((u) => {
              const self = u.id === me!.user.id;
              const locked = self || (u.role === "owner" && !can("owner"));
              return (
                <li key={u.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{u.full_name} {self && <Badge>You</Badge>} {!u.is_active && <Badge tone="bad">Disabled</Badge>}</div>
                    <div className="text-xs text-ink-3">{u.email}</div>
                  </div>
                  <Select className="w-32" value={u.role} disabled={locked} onChange={(e) => update(u, { role: e.target.value as Role })} aria-label={`Role for ${u.full_name}`}>
                    {(locked ? ROLES : assignable).map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
                  </Select>
                  {!locked && (
                    <Button size="sm" variant={u.is_active ? "danger" : "secondary"} onClick={() => update(u, { is_active: !u.is_active })}>
                      {u.is_active ? "Disable" : "Enable"}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <p className="mt-3 text-xs text-ink-3">Viewers can see calls and settings. Members can also manage knowledge and appointments. Admins can change agents, numbers and the team.</p>

      <Modal open={inviting} onClose={() => setInviting(false)} title="Add team member"
        footer={<><Button onClick={() => setInviting(false)}>Cancel</Button><Button variant="primary" type="submit" form="invite" loading={busy}>Add</Button></>}>
        <form id="invite" onSubmit={invite} className="space-y-4">
          {formError && <ErrorBox message={formError} />}
          <Field label="Full name"><Input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="Email"><Input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Temporary password" hint="At least 10 characters. Share it with them securely.">
            <Input type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label="Role">
            <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {assignable.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
            </Select>
          </Field>
        </form>
      </Modal>
    </>
  );
}

function AuditView() {
  const [filter, setFilter] = useState("");
  const { data, error, loading, reload } = useApi<AuditEntry[]>("/audit-logs", { limit: 200, action: filter || undefined });
  return (
    <Card title="Activity log" action={
      <Select className="h-8 w-auto text-xs" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter activity">
        <option value="">Everything</option>
        <option value="auth">Sign-ins</option>
        <option value="agent">Agent changes</option>
        <option value="knowledge">Knowledge base</option>
        <option value="appointment">Appointments</option>
        <option value="voice_agent">AI agent actions</option>
        <option value="call">Calls</option>
        <option value="user">Team</option>
      </Select>
    }>
      {error && <div className="p-4"><ErrorBox message={error} onRetry={reload} /></div>}
      {loading && !data ? <Loading /> : !data?.length ? <Empty icon={<ScrollText className="size-6" />} title="No activity yet" /> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-3">
              <tr className="border-b border-line">
                <th className="px-5 py-2.5 font-medium">When</th><th className="px-3 py-2.5 font-medium">Action</th>
                <th className="px-3 py-2.5 font-medium">By</th><th className="px-5 py-2.5 font-medium">IP</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap px-5 py-2.5 text-ink-2">{fmtDateTime(e.created_at)}</td>
                  <td className="px-3 py-2.5 font-mono text-xs">{e.action}</td>
                  <td className="px-3 py-2.5 text-ink-2">{humanize(e.actor)}</td>
                  <td className="px-5 py-2.5 text-xs text-ink-3">{e.ip_address ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export default function SettingsPage() {
  const { can } = useAuth();
  const [view, setView] = useState<View>("organization");
  const items: { value: View; label: string }[] = [{ value: "organization", label: "Business" }];
  if (can("admin")) items.push({ value: "team", label: "Team" });
  if (can("member")) items.push({ value: "audit", label: "Activity" });

  return (
    <>
      <PageHeader title="Settings" actions={items.length > 1 && <Tabs<View> value={view} onChange={setView} items={items} />} />
      {view === "organization" && <OrganizationView />}
      {view === "team" && <TeamView />}
      {view === "audit" && <AuditView />}
    </>
  );
}
