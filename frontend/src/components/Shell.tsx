"use client";

import clsx from "clsx";
import {
  AudioLines, BookOpen, Bot, Calendar, History, LayoutDashboard, LogOut, Menu, Phone, Radio, Settings, Wrench, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Loading } from "./ui";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/live-calls", label: "Live Calls", icon: Radio },
  { href: "/calls", label: "Call History", icon: History },
  { href: "/agent", label: "AI Agent", icon: Bot },
  { href: "/knowledge", label: "Knowledge Base", icon: BookOpen },
  { href: "/calendar", label: "Calendar", icon: Calendar },
  { href: "/phone-numbers", label: "Phone Numbers", icon: Phone },
  { href: "/tools", label: "Tools", icon: Wrench },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const { me, loading, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  useEffect(() => setOpen(false), [pathname]);

  if (loading || !me) return <Loading />;

  const active = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

  const nav = (
    <nav className="flex flex-1 flex-col gap-0.5 px-3">
      {NAV.map(({ href, label, icon: Icon }) => (
        <Link
          key={href}
          href={href}
          className={clsx(
            "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
            active(href) ? "bg-accent-soft text-accent" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
          )}
        >
          <Icon className="size-4" />
          {label}
        </Link>
      ))}
    </nav>
  );

  const footer = (
    <div className="border-t border-line p-3">
      <div className="px-3 py-2">
        <div className="truncate text-sm font-medium">{me.organization.name}</div>
        <div className="truncate text-xs text-ink-3">{me.user.email} · {me.user.role}</div>
      </div>
      <button onClick={logout} className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-ink-2 hover:bg-surface-2">
        <LogOut className="size-4" /> Sign out
      </button>
    </div>
  );

  const brand = (
    <div className="flex items-center gap-2 px-6 py-5">
      <div className="flex size-8 items-center justify-center rounded-lg bg-accent text-white"><AudioLines className="size-4" /></div>
      <span className="font-semibold tracking-tight">VoiceDesk</span>
    </div>
  );

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface lg:flex">
        {brand}
        {nav}
        {footer}
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <aside className="absolute inset-y-0 left-0 flex w-64 flex-col bg-surface" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between pr-3">
              {brand}
              <button onClick={() => setOpen(false)} aria-label="Close menu" className="rounded p-1.5 hover:bg-surface-2"><X className="size-4" /></button>
            </div>
            {nav}
            {footer}
          </aside>
        </div>
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-surface/90 px-4 py-3 backdrop-blur lg:hidden">
          <button onClick={() => setOpen(true)} aria-label="Open menu" className="rounded p-1.5 hover:bg-surface-2"><Menu className="size-5" /></button>
          <span className="font-semibold">VoiceDesk</span>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
      </div>
    </div>
  );
}
