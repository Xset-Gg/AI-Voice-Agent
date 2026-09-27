"use client";

import Link from "next/link";
import { Badge, Card, ErrorBox, Loading, PageHeader } from "@/components/ui";
import { useAgents } from "@/lib/agents";
import { humanize } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ToolSpec } from "@/lib/types";

export default function ToolsPage() {
  const { data: tools, error, loading, reload } = useApi<ToolSpec[]>("/tools");
  const agents = useAgents();
  const categories = [...new Set(tools?.map((t) => t.category) ?? [])];

  const enabledFor = (t: ToolSpec) =>
    (agents.data ?? []).filter((a) => t.always_on || (a.allowed_actions.includes(t.name) && (t.name !== "transfer_to_human" || a.transfer_enabled)));

  return (
    <>
      <PageHeader
        title="Tools"
        description="Actions your agents can take during a call. Every action is re-checked by the server — the AI can't do anything you haven't allowed."
      />
      {error && <ErrorBox message={error} onRetry={reload} />}
      {loading && !tools ? <Loading /> : (
        <div className="space-y-4">
          {categories.map((cat) => (
            <Card key={cat} title={humanize(cat)}>
              <ul className="divide-y divide-line">
                {tools!.filter((t) => t.category === cat).map((t) => {
                  const on = enabledFor(t);
                  return (
                    <li key={t.name} className="flex flex-wrap items-start gap-3 px-5 py-3.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                          {t.title}
                          {t.always_on && <Badge>Always on</Badge>}
                          {t.mutates && <Badge tone="warn">Changes data</Badge>}
                        </div>
                        <p className="mt-0.5 text-sm text-ink-2">{t.description}</p>
                        {t.requires.length > 0 && <p className="mt-0.5 text-xs text-ink-3">Needs: {t.requires.map(humanize).join(", ")}</p>}
                      </div>
                      <div className="text-right text-xs text-ink-3">
                        {agents.data && (on.length ? `Enabled for ${on.map((a) => a.name).join(", ")}` : "Not enabled")}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </Card>
          ))}
          <p className="text-sm text-ink-3">Turn actions on or off per agent in <Link href="/agent" className="text-accent hover:underline">AI Agents → Actions</Link>.</p>
        </div>
      )}
    </>
  );
}
