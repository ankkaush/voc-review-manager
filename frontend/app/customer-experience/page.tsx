"use client";

import { useEffect, useState } from "react";
import { DashboardShellNoSSR as DashboardShell } from "@/components/DashboardShellClient";
import { api } from "@/lib/api";
import type { AspectSummary, AspectsResponse } from "@/lib/types";

function AspectRow({ aspect, kind }: { aspect: AspectSummary; kind: "negative" | "positive" }) {
  const count = kind === "negative" ? aspect.negative_count : aspect.positive_count;
  const barColor = kind === "negative" ? "bg-red-500" : "bg-emerald-500";
  const max = kind === "negative" ? aspect.mention_count : aspect.mention_count;
  const pct = max > 0 ? Math.round((count / max) * 100) : 0;

  return (
    <div className="mb-3">
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="font-medium text-slate-700">{aspect.aspect_label}</span>
        <span className="text-slate-500">
          {count} of {aspect.mention_count} mentions
        </span>
      </div>
      <div className="h-2 w-full rounded-full bg-slate-100">
        <div className={`h-2 rounded-full ${barColor}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-0.5 text-xs text-slate-400">{aspect.topic_label}</div>
    </div>
  );
}

function CustomerExperienceContent({ businessId }: { businessId: string }) {
  const [aspects, setAspects] = useState<AspectsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // businessId changes remount this component (DashboardShell keys on it).
    api
      .get<AspectsResponse>(`/analytics/aspects?business_id=${businessId}&limit=10`)
      .then(setAspects)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load aspects"));
  }, [businessId]);

  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (!aspects) return <p className="text-slate-500">Loading...</p>;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Customer Experience</h1>
        <p className="mt-1 text-sm text-slate-500">
          What specific aspects of the experience customers praise or complain about most.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-700">Top negative aspects</h2>
          {aspects.top_negative.length === 0 && <p className="text-sm text-slate-400">No negative aspects yet.</p>}
          {aspects.top_negative.map((a) => (
            <AspectRow key={`${a.topic_key}-${a.aspect_key}`} aspect={a} kind="negative" />
          ))}
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-4 text-sm font-semibold text-slate-700">Top positive aspects</h2>
          {aspects.top_positive.length === 0 && <p className="text-sm text-slate-400">No positive aspects yet.</p>}
          {aspects.top_positive.map((a) => (
            <AspectRow key={`${a.topic_key}-${a.aspect_key}`} aspect={a} kind="positive" />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function CustomerExperiencePage() {
  return <DashboardShell>{(businessId) => <CustomerExperienceContent businessId={businessId} />}</DashboardShell>;
}
