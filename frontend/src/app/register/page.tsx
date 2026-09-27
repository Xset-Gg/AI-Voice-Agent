"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AuthCard } from "@/components/AuthCard";
import { Button, ErrorBox, Field, Input } from "@/components/ui";
import { useAuth } from "@/lib/auth";

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ organization_name: "", full_name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await register({ ...form, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" });
      router.replace("/agent");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <AuthCard
      title="Create your business account"
      subtitle="You'll get a ready-to-customise AI receptionist."
      footer={<>Already have an account? <Link href="/login" className="font-medium text-accent hover:underline">Sign in</Link></>}
    >
      <form onSubmit={submit} className="space-y-4">
        {error && <ErrorBox message={error} />}
        <Field label="Business name"><Input required minLength={2} value={form.organization_name} onChange={set("organization_name")} /></Field>
        <Field label="Your name"><Input required autoComplete="name" value={form.full_name} onChange={set("full_name")} /></Field>
        <Field label="Email"><Input type="email" required autoComplete="email" value={form.email} onChange={set("email")} /></Field>
        <Field label="Password" hint="At least 10 characters, with letters and numbers.">
          <Input type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={set("password")} />
        </Field>
        <Button variant="primary" type="submit" loading={busy} className="w-full">Create account</Button>
      </form>
    </AuthCard>
  );
}
