"use client";

import clsx from "clsx";
import { CalendarDays, CalendarPlus, ChevronLeft, ChevronRight, Link2, Pencil, Plus, Trash2, UserRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { WorkingHoursEditor } from "@/components/WorkingHoursEditor";
import { Badge, Button, Card, Empty, ErrorBox, Field, Input, Loading, Modal, PageHeader, Select, Tabs, Textarea, Toggle } from "@/components/ui";
import { timezoneOptions } from "@/lib/agents";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtPhone, fmtTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Appointment, Slot, Technician, WorkingHours } from "@/lib/types";

type View = "appointments" | "technicians" | "integrations";

const DEFAULT_HOURS: WorkingHours = {
  mon: [["09:00", "17:00"]], tue: [["09:00", "17:00"]], wed: [["09:00", "17:00"]], thu: [["09:00", "17:00"]], fri: [["09:00", "17:00"]], sat: [], sun: [],
};

function startOfWeek(d: Date) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Pick a technician + day, show the open slots from the backend. */
function SlotPicker({ technicians, technicianId, onTechnician, duration, value, onChange, lockTechnician }: {
  technicians: Technician[]; technicianId: string; onTechnician: (id: string) => void; duration: number;
  value: Slot | null; onChange: (s: Slot | null) => void; lockTechnician?: boolean;
}) {
  const [day, setDay] = useState(isoDay(new Date()));
  const slots = useApi<Slot[]>("/availability", { day, technician_id: technicianId || undefined, duration_minutes: duration });

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Technician">
          <Select value={technicianId} disabled={lockTechnician} onChange={(e) => { onTechnician(e.target.value); onChange(null); }}>
            {!lockTechnician && <option value="">Any available</option>}
            {technicians.filter((t) => t.is_active || t.id === technicianId).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </Select>
        </Field>
        <Field label="Day"><Input type="date" value={day} min={isoDay(new Date())} onChange={(e) => { setDay(e.target.value); onChange(null); }} /></Field>
      </div>
      <div>
        <div className="mb-1.5 text-xs font-medium text-ink-2">Open times</div>
        {slots.error ? <ErrorBox message={slots.error} /> : slots.loading ? <Loading /> : !slots.data?.length ? (
          <p className="rounded-lg bg-surface-2 p-3 text-sm text-ink-3">No open times that day.</p>
        ) : (
          <div className="flex max-h-48 flex-wrap gap-1.5 overflow-y-auto">
            {slots.data.map((s) => {
              const on = value?.starts_at === s.starts_at && value.technician_id === s.technician_id;
              return (
                <button type="button" key={s.technician_id + s.starts_at} onClick={() => onChange(s)}
                  className={clsx("rounded-md border px-2.5 py-1 text-xs font-medium tabular-nums", on ? "border-accent bg-accent text-white" : "border-line hover:bg-surface-2")}>
                  {fmtTime(s.starts_at)}{!technicianId && <span className={on ? "text-white/80" : "text-ink-3"}> · {s.technician_name}</span>}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function BookModal({ open, onClose, technicians, onBooked }: { open: boolean; onClose: () => void; technicians: Technician[]; onBooked: () => void }) {
  const [tech, setTech] = useState("");
  const [slot, setSlot] = useState<Slot | null>(null);
  const [duration, setDuration] = useState(60);
  const [form, setForm] = useState({ customer_phone: "", customer_name: "", service: "", notes: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!slot) return setError("Pick a time");
    setBusy(true);
    setError(null);
    try {
      await api("/appointments", { body: { ...form, technician_id: slot.technician_id, starts_at: slot.starts_at, duration_minutes: duration } });
      onBooked();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title="Book appointment" wide
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="book" loading={busy} disabled={!slot}>Book</Button></>}>
      <form id="book" onSubmit={submit} className="space-y-4">
        {error && <ErrorBox message={error} />}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Service"><Input required maxLength={200} value={form.service} onChange={(e) => setForm({ ...form, service: e.target.value })} placeholder="AC repair" /></Field>
          <Field label="Length (minutes)"><Input type="number" min={10} max={480} step={5} value={duration} onChange={(e) => { setDuration(Number(e.target.value) || 60); setSlot(null); }} /></Field>
          <Field label="Customer phone"><Input required value={form.customer_phone} onChange={(e) => setForm({ ...form, customer_phone: e.target.value })} placeholder="+15551234567" /></Field>
          <Field label="Customer name"><Input maxLength={200} value={form.customer_name} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} /></Field>
        </div>
        <SlotPicker technicians={technicians} technicianId={tech} onTechnician={setTech} duration={duration} value={slot} onChange={setSlot} />
        <Field label="Notes"><Textarea rows={2} maxLength={2000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></Field>
      </form>
    </Modal>
  );
}

function AppointmentModal({ appt, technicians, onClose, onChanged }: { appt: Appointment | null; technicians: Technician[]; onClose: () => void; onChanged: () => void }) {
  const { can } = useAuth();
  const [mode, setMode] = useState<"view" | "reschedule">("view");
  const [slot, setSlot] = useState<Slot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!appt) return null;
  const duration = Math.round((new Date(appt.ends_at).getTime() - new Date(appt.starts_at).getTime()) / 60000);

  const act = async (path: string, body?: unknown) => {
    setBusy(true);
    setError(null);
    try {
      await api(`/appointments/${appt.id}/${path}`, { method: "POST", body });
      onChanged();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const editable = can("member") && appt.status === "scheduled";
  return (
    <Modal open onClose={onClose} title={appt.service} wide
      footer={editable && (mode === "view" ? (
        <><Button variant="danger" loading={busy} onClick={() => act("cancel")}>Cancel appointment</Button><Button onClick={() => setMode("reschedule")}>Reschedule</Button></>
      ) : (
        <><Button onClick={() => setMode("view")}>Back</Button><Button variant="primary" loading={busy} disabled={!slot} onClick={() => act("reschedule", { starts_at: slot!.starts_at })}>Move here</Button></>
      ))}>
      <div className="space-y-4 text-sm">
        {error && <ErrorBox message={error} />}
        {mode === "view" ? (
          <dl className="grid grid-cols-[8rem_1fr] gap-y-2">
            <dt className="text-ink-3">When</dt>
            <dd>{new Date(appt.starts_at).toLocaleString(undefined, { weekday: "long", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })} – {fmtTime(appt.ends_at)}</dd>
            <dt className="text-ink-3">Technician</dt><dd>{appt.technician.name}</dd>
            <dt className="text-ink-3">Customer</dt><dd>{appt.customer ? `${appt.customer.name || "—"} · ${fmtPhone(appt.customer.phone)}` : "—"}</dd>
            <dt className="text-ink-3">Status</dt><dd><Badge tone={appt.status === "scheduled" ? "good" : "neutral"}>{appt.status}</Badge></dd>
            <dt className="text-ink-3">Booked via</dt><dd>{appt.created_via === "voice_agent" ? "AI agent (phone)" : appt.created_via}</dd>
            {appt.notes && <><dt className="text-ink-3">Notes</dt><dd className="whitespace-pre-wrap">{appt.notes}</dd></>}
          </dl>
        ) : (
          <SlotPicker technicians={technicians} technicianId={appt.technician_id} onTechnician={() => {}} lockTechnician duration={duration} value={slot} onChange={setSlot} />
        )}
      </div>
    </Modal>
  );
}

function AppointmentsView({ technicians }: { technicians: Technician[] }) {
  const { can } = useAuth();
  const [week, setWeek] = useState(() => startOfWeek(new Date()));
  const [techFilter, setTechFilter] = useState("");
  const [booking, setBooking] = useState(false);
  const [open, setOpen] = useState<Appointment | null>(null);
  const { data, error, loading, reload } = useApi<Appointment[]>("/appointments", {
    start: week.toISOString(), end: addDays(week, 7).toISOString(), technician_id: techFilter || undefined,
  });
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(week, i)), [week]);
  const today = isoDay(new Date());

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => setWeek(addDays(week, -7))} aria-label="Previous week"><ChevronLeft className="size-4" /></Button>
        <Button size="sm" onClick={() => setWeek(startOfWeek(new Date()))}>This week</Button>
        <Button size="sm" onClick={() => setWeek(addDays(week, 7))} aria-label="Next week"><ChevronRight className="size-4" /></Button>
        <span className="text-sm font-medium">
          {week.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – {addDays(week, 6).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
        </span>
        <div className="flex-1" />
        <Select className="w-auto" value={techFilter} onChange={(e) => setTechFilter(e.target.value)} aria-label="Technician filter">
          <option value="">All technicians</option>
          {technicians.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </Select>
        {can("member") && <Button variant="primary" size="sm" disabled={!technicians.length} onClick={() => setBooking(true)}><CalendarPlus className="size-4" /> Book</Button>}
      </div>
      {error && <ErrorBox message={error} onRetry={reload} />}
      {!technicians.length && (
        <Card><Empty icon={<UserRound className="size-6" />} title="Add a technician first" description="Appointments are booked against a technician's working hours." /></Card>
      )}
      {technicians.length > 0 && (loading && !data ? <Loading /> : (
        <div className="grid gap-3 md:grid-cols-7">
          {days.map((d) => {
            const items = (data ?? []).filter((a) => isoDay(new Date(a.starts_at)) === isoDay(d));
            return (
              <div key={d.toISOString()} className={clsx("min-h-32 rounded-xl border bg-surface", isoDay(d) === today ? "border-accent" : "border-line")}>
                <div className="border-b border-line px-3 py-2 text-xs font-medium text-ink-2">
                  {d.toLocaleDateString(undefined, { weekday: "short" })} <span className="text-ink">{d.getDate()}</span>
                </div>
                <div className="space-y-1.5 p-2">
                  {items.map((a) => (
                    <button key={a.id} onClick={() => setOpen(a)}
                      className={clsx("w-full rounded-md px-2 py-1.5 text-left text-xs hover:opacity-80", a.created_via === "voice_agent" ? "bg-accent-soft" : "bg-surface-2")}>
                      <div className="font-medium tabular-nums">{fmtTime(a.starts_at)}</div>
                      <div className="truncate">{a.service}</div>
                      <div className="truncate text-ink-3">{a.technician.name}</div>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      ))}
      <p className="mt-3 text-xs text-ink-3"><span className="mr-1 inline-block size-2.5 rounded-sm bg-accent-soft align-middle" /> Booked by the AI agent</p>
      <BookModal open={booking} onClose={() => setBooking(false)} technicians={technicians} onBooked={reload} />
      <AppointmentModal key={open?.id} appt={open} technicians={technicians} onClose={() => setOpen(null)} onChanged={reload} />
    </>
  );
}

function TechnicianModal({ tech, open, onClose, onSaved, googleConnected }: { tech: Technician | null; open: boolean; onClose: () => void; onSaved: () => void; googleConnected: boolean }) {
  const { me } = useAuth();
  const calendars = useApi<{ id: string; summary: string; primary: boolean }[]>(open && googleConnected ? "/integrations/google/calendars" : null);
  const [form, setForm] = useState(() => ({
    name: tech?.name ?? "", email: tech?.email ?? "", skills: tech?.skills.join(", ") ?? "",
    calendar_provider: tech?.calendar_provider ?? "internal", calendar_id: tech?.calendar_id ?? "",
    timezone: tech?.timezone ?? me?.organization.timezone ?? "UTC",
    working_hours: tech && Object.keys(tech.working_hours).length ? tech.working_hours : DEFAULT_HOURS,
    is_active: tech?.is_active ?? true,
  }));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        ...form, email: form.email || null, calendar_id: form.calendar_provider === "google" ? form.calendar_id : null,
        skills: form.skills.split(",").map((s) => s.trim()).filter(Boolean),
      };
      await api(tech ? `/technicians/${tech.id}` : "/technicians", { method: tech ? "PUT" : "POST", body });
      onSaved();
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open onClose={onClose} title={tech ? `Edit ${tech.name}` : "Add technician"} wide
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" type="submit" form="tech" loading={busy}>Save</Button></>}>
      <form id="tech" onSubmit={submit} className="space-y-4">
        {error && <ErrorBox message={error} />}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Name"><Input required maxLength={200} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Email"><Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Skills" hint="Comma separated. The agent matches these to the requested service.">
            <Input value={form.skills} onChange={(e) => setForm({ ...form, skills: e.target.value })} placeholder="hvac, plumbing" />
          </Field>
          <Field label="Timezone">
            <Select value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })}>
              {timezoneOptions(form.timezone).map((tz) => <option key={tz}>{tz}</option>)}
            </Select>
          </Field>
          <Field label="Calendar">
            <Select value={form.calendar_provider} onChange={(e) => setForm({ ...form, calendar_provider: e.target.value as Technician["calendar_provider"] })}>
              <option value="internal">Built-in calendar</option>
              <option value="google" disabled={!googleConnected}>Google Calendar{googleConnected ? "" : " (connect first)"}</option>
            </Select>
          </Field>
          {form.calendar_provider === "google" && (
            <Field label="Google calendar">
              <Select required value={form.calendar_id} onChange={(e) => setForm({ ...form, calendar_id: e.target.value })}>
                <option value="">Choose…</option>
                {calendars.data?.map((c) => <option key={c.id} value={c.id}>{c.summary}{c.primary ? " (primary)" : ""}</option>)}
              </Select>
            </Field>
          )}
        </div>
        <Toggle label="Available for booking" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
        <div>
          <div className="mb-1 text-xs font-medium text-ink-2">Working hours</div>
          <WorkingHoursEditor value={form.working_hours} onChange={(v) => setForm({ ...form, working_hours: v })} />
        </div>
      </form>
    </Modal>
  );
}

function TechniciansView({ technicians, reload, googleConnected }: { technicians: Technician[]; reload: () => void; googleConnected: boolean }) {
  const { can } = useAuth();
  const [editing, setEditing] = useState<Technician | null | "new">(null);
  const [error, setError] = useState<string | null>(null);

  const remove = async (t: Technician) => {
    setError(null);
    try {
      await api(`/technicians/${t.id}`, { method: "DELETE" });
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      {error && <div className="mb-4"><ErrorBox message={error} /></div>}
      <Card title="Technicians" action={can("admin") && <Button size="sm" variant="primary" onClick={() => setEditing("new")}><Plus className="size-3.5" /> Add</Button>}>
        {!technicians.length ? <Empty icon={<UserRound className="size-6" />} title="No technicians yet" description="Add the people customers can book." /> : (
          <ul className="divide-y divide-line">
            {technicians.map((t) => (
              <li key={t.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{t.name} {!t.is_active && <Badge>Inactive</Badge>}</div>
                  <div className="text-xs text-ink-3">{t.skills.join(", ") || "No skills listed"} · {t.calendar_provider === "google" ? "Google Calendar" : "Built-in calendar"} · {t.timezone}</div>
                </div>
                {can("admin") && (
                  <>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(t)} aria-label={`Edit ${t.name}`}><Pencil className="size-3.5" /></Button>
                    <Button size="sm" variant="ghost" onClick={() => remove(t)} aria-label={`Delete ${t.name}`}><Trash2 className="size-3.5" /></Button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <TechnicianModal key={editing === "new" ? "new" : editing?.id ?? "none"} open={editing !== null} tech={editing === "new" ? null : editing}
        onClose={() => setEditing(null)} onSaved={reload} googleConnected={googleConnected} />
    </>
  );
}

function IntegrationsView({ connected, email, reload }: { connected: boolean; email?: string; reload: () => void }) {
  const { can } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async () => {
    setBusy(true);
    setError(null);
    try {
      const { authorization_url } = await api<{ authorization_url: string }>("/integrations/google/authorize", { method: "POST" });
      window.location.href = authorization_url;
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };
  const disconnect = async () => {
    setBusy(true);
    setError(null);
    try {
      await api("/integrations/google", { method: "DELETE" });
      reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="Google Calendar">
      <div className="flex flex-wrap items-center justify-between gap-4 p-5">
        <div className="text-sm">
          {connected ? <>Connected as <span className="font-medium">{email || "Google account"}</span>. Technicians can now sync to their Google calendars.</>
            : "Connect Google so bookings appear on your technicians' real calendars and their busy times are respected."}
        </div>
        {can("admin") && (connected
          ? <Button variant="danger" loading={busy} onClick={disconnect}>Disconnect</Button>
          : <Button variant="primary" loading={busy} onClick={connect}><Link2 className="size-4" /> Connect Google</Button>)}
      </div>
      {error && <div className="px-5 pb-5"><ErrorBox message={error} /></div>}
    </Card>
  );
}

const GOOGLE_MESSAGES: Record<string, { ok: boolean; text: string }> = {
  connected: { ok: true, text: "Google Calendar connected." },
  error: { ok: false, text: "Google sign-in was cancelled or failed." },
  invalid_state: { ok: false, text: "The Google sign-in link expired. Please try again." },
  no_refresh_token: { ok: false, text: "Google didn't grant offline access. Remove the app at myaccount.google.com/permissions and connect again." },
};

export default function CalendarPage() {
  const [view, setView] = useState<View>("appointments");
  const techs = useApi<Technician[]>("/technicians");
  const integrations = useApi<{ id: string; provider: string; account_email: string }[]>("/integrations");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  // One-shot read of the Google OAuth redirect result from the URL (client-only, so not in initial state).
  useEffect(() => {
    const g = new URLSearchParams(window.location.search).get("google");
    if (g && GOOGLE_MESSAGES[g]) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setNotice(GOOGLE_MESSAGES[g]);
      setView("integrations");
      window.history.replaceState(null, "", "/calendar");
    }
  }, []);

  const google = integrations.data?.find((i) => i.provider === "google");

  return (
    <>
      <PageHeader
        title="Calendar"
        description="Appointments booked by your agent and your team."
        actions={<Tabs<View> value={view} onChange={setView} items={[
          { value: "appointments", label: "Appointments" }, { value: "technicians", label: "Technicians" }, { value: "integrations", label: "Integrations" },
        ]} />}
      />
      {notice && (
        <div className={clsx("mb-4 rounded-lg px-4 py-3 text-sm", notice.ok ? "bg-good-soft text-good" : "bg-bad-soft text-bad")}>{notice.text}</div>
      )}
      {techs.error && <ErrorBox message={techs.error} onRetry={techs.reload} />}
      {techs.loading && !techs.data ? <Loading /> : (
        <>
          {view === "appointments" && <AppointmentsView technicians={techs.data ?? []} />}
          {view === "technicians" && <TechniciansView technicians={techs.data ?? []} reload={techs.reload} googleConnected={!!google} />}
          {view === "integrations" && <IntegrationsView connected={!!google} email={google?.account_email} reload={integrations.reload} />}
        </>
      )}
      {!techs.loading && view === "appointments" && techs.data?.length === 0 && (
        <div className="mt-3"><Button size="sm" onClick={() => setView("technicians")}><CalendarDays className="size-4" /> Manage technicians</Button></div>
      )}
    </>
  );
}
