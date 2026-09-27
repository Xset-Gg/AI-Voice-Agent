import { AudioLines } from "lucide-react";

export function AuthCard({ title, subtitle, children, footer }: { title: string; subtitle: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center justify-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-accent text-white"><AudioLines className="size-5" /></div>
          <span className="text-lg font-semibold tracking-tight">VoiceDesk</span>
        </div>
        <div className="rounded-xl border border-line bg-surface p-6 shadow-sm">
          <h1 className="text-lg font-semibold">{title}</h1>
          <p className="mb-5 mt-1 text-sm text-ink-2">{subtitle}</p>
          {children}
        </div>
        <p className="mt-4 text-center text-sm text-ink-2">{footer}</p>
      </div>
    </div>
  );
}
