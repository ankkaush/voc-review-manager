"use client";

import { useEffect, useState } from "react";
import { DashboardShellNoSSR as DashboardShell } from "@/components/DashboardShellClient";
import { StatusBadge } from "@/components/Badge";
import { api } from "@/lib/api";
import type { ProcessingRun } from "@/lib/types";

function fmtDate(s: string | null) {
  return s ? new Date(s).toLocaleString() : "—";
}

function durationSeconds(started: string | null, finished: string | null): string {
  if (!started || !finished) return "—";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  return `${(ms / 1000).toFixed(1)}s`;
}

function SystemHealthContent() {
  const [runs, setRuns] = useState<ProcessingRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<ProcessingRun[]>("/system-health/runs")
      .then(setRuns)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load runs"));
  }, []);

  if (error) return <p className="text-red-600">Error: {error}</p>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">System Health</h1>
        <p className="mt-1 text-sm text-slate-500">
          Technical observability — is the automation working, not what customers are saying.
          Deliberately separate from the business dashboard.
        </p>
      </div>

      {!runs && <p className="text-slate-500">Loading...</p>}

      {runs && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Job</th>
                <th className="px-4 py-3">Trigger</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Started</th>
                <th className="px-4 py-3">Duration</th>
                <th className="px-4 py-3">In scope</th>
                <th className="px-4 py-3">Succeeded</th>
                <th className="px-4 py-3">Failed</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-3 font-medium text-slate-800">{run.job_type}</td>
                  <td className="px-4 py-3 text-slate-500">{run.trigger}</td>
                  <td className="px-4 py-3">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="px-4 py-3 text-slate-500">{fmtDate(run.started_at)}</td>
                  <td className="px-4 py-3 text-slate-500">{durationSeconds(run.started_at, run.finished_at)}</td>
                  <td className="px-4 py-3 text-slate-500">{run.reviews_in_scope}</td>
                  <td className="px-4 py-3 text-emerald-600">{run.reviews_succeeded}</td>
                  <td className="px-4 py-3 text-red-600">{run.reviews_failed}</td>
                </tr>
              ))}
              {runs.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-slate-400">
                    No processing runs yet.
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

export default function SystemHealthPage() {
  return <DashboardShell>{() => <SystemHealthContent />}</DashboardShell>;
}
