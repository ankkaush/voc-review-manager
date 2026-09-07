"use client";

import { useEffect, useState } from "react";
import { DashboardShellNoSSR as DashboardShell } from "@/components/DashboardShellClient";
import { DistributionBarChart } from "@/components/DistributionBarChart";
import { StatCard } from "@/components/StatCard";
import { api } from "@/lib/api";
import type { Overview } from "@/lib/types";

function toChartData(record: Record<string, number>, order?: string[]): { name: string; count: number }[] {
  const keys = order ? order.filter((k) => k in record) : Object.keys(record);
  return keys.map((name) => ({ name, count: record[name] }));
}

function OverviewContent({ businessId }: { businessId: string }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // businessId changes remount this component (DashboardShell keys on it), so
    // `overview` always starts null here — no manual reset needed.
    api
      .get<Overview>(`/analytics/overview?business_id=${businessId}`)
      .then(setOverview)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load overview"));
  }, [businessId]);

  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (!overview) return <p className="text-slate-500">Loading overview...</p>;

  const analyzed = overview.analysis_status_counts.analyzed ?? 0;
  const pending = overview.analysis_status_counts.pending ?? 0;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">Feedback Overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          What customers are saying, at a glance — computed directly from ingested reviews.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Total reviews" value={overview.review_count} />
        <StatCard label="Analyzed" value={analyzed} sublabel={`${pending} pending analysis`} />
        <StatCard
          label="Negative sentiment"
          value={overview.sentiment_distribution.negative ?? 0}
          sublabel={`of ${analyzed} analyzed`}
        />
        <StatCard
          label="Languages detected"
          value={Object.keys(overview.language_distribution).length}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Rating distribution</h2>
          <DistributionBarChart
            data={toChartData(overview.rating_distribution, ["1", "2", "3", "4", "5"])}
            color="#f59e0b"
          />
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">
            Sentiment distribution <span className="font-normal text-slate-400">(analyzed reviews only)</span>
          </h2>
          <DistributionBarChart
            data={toChartData(overview.sentiment_distribution, ["positive", "mixed", "neutral", "negative"])}
            color="#0ea5e9"
          />
        </div>

        <div className="rounded-lg border border-slate-200 bg-white p-5 lg:col-span-2">
          <h2 className="mb-3 text-sm font-semibold text-slate-700">Language distribution</h2>
          <DistributionBarChart data={toChartData(overview.language_distribution)} color="#8b5cf6" />
        </div>
      </div>
    </div>
  );
}

export default function OverviewPage() {
  return <DashboardShell>{(businessId) => <OverviewContent businessId={businessId} />}</DashboardShell>;
}
