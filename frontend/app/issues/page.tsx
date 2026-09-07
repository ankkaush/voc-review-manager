"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DashboardShellNoSSR as DashboardShell } from "@/components/DashboardShellClient";
import { SeverityBadge, StatusBadge, TrendBadge } from "@/components/Badge";
import { api } from "@/lib/api";
import type { Issue, Location } from "@/lib/types";

const STATUS_FILTERS = [
  "all",
  "identified",
  "reviewed",
  "recommended",
  "awaiting_approval",
  "approved",
  "action_created",
  "resolved",
  "monitoring",
  "closed",
  "rejected",
];

function IssuesContent({ businessId }: { businessId: string }) {
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [locations, setLocations] = useState<Location[]>([]);
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // businessId changes remount this component (DashboardShell keys on it).
    Promise.all([
      api.get<Issue[]>(`/issues?business_id=${businessId}`),
      api.get<Location[]>(`/businesses/${businessId}/locations`),
    ])
      .then(([issueList, locationList]) => {
        setIssues(issueList);
        setLocations(locationList);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load issues"));
  }, [businessId]);

  const locationName = useMemo(() => {
    const map = new Map(locations.map((l) => [l.id, l.name]));
    return (id: string | null) => (id ? (map.get(id) ?? id) : "All locations");
  }, [locations]);

  const filtered = useMemo(() => {
    if (!issues) return [];
    const sorted = [...issues].sort((a, b) => (b.priority_score ?? -1) - (a.priority_score ?? -1));
    return statusFilter === "all" ? sorted : sorted.filter((i) => i.status === statusFilter);
  }, [issues, statusFilter]);

  if (error) return <p className="text-red-600">Error: {error}</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Issues</h1>
          <p className="mt-1 text-sm text-slate-500">
            Recurring problems the system has identified, ranked by priority.
          </p>
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
        >
          {STATUS_FILTERS.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All statuses" : s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      {!issues && <p className="text-slate-500">Loading issues...</p>}

      {issues && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Issue</th>
                <th className="px-4 py-3">Location</th>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Trend</th>
                <th className="px-4 py-3">Priority</th>
                <th className="px-4 py-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((issue) => (
                <tr key={issue.id} className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <Link href={`/issues/${issue.id}`} className="font-medium text-slate-900 hover:underline">
                      {issue.title}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-600">{locationName(issue.location_id)}</td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={issue.severity} />
                  </td>
                  <td className="px-4 py-3">
                    <TrendBadge direction={issue.trend_direction} changePct={issue.trend_change_pct} />
                  </td>
                  <td className="px-4 py-3 text-slate-600">
                    {issue.priority_score !== null ? issue.priority_score.toFixed(2) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={issue.status} />
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-slate-400">
                    No issues match this filter.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function IssuesPage() {
  return <DashboardShell>{(businessId) => <IssuesContent businessId={businessId} />}</DashboardShell>;
}
