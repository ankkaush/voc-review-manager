"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { DashboardShellNoSSR as DashboardShell } from "@/components/DashboardShellClient";
import { StatusBadge } from "@/components/Badge";
import { api } from "@/lib/api";
import type { Action } from "@/lib/types";

const STATUS_FILTERS = [
  "all",
  "recommended",
  "awaiting_approval",
  "approved",
  "action_created",
  "resolved",
  "rejected",
];

function ActionsContent({ businessId }: { businessId: string }) {
  const [actions, setActions] = useState<Action[] | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .get<Action[]>(`/actions?business_id=${businessId}`)
      .then(setActions)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load actions"));
  }, [businessId]);

  useEffect(() => {
    // businessId changes remount this component (DashboardShell keys on it).
    reload();
  }, [reload]);

  async function quickApprove(action: Action) {
    setBusyId(action.id);
    try {
      await api.post(`/actions/${action.id}/approve`, {});
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approve failed");
    } finally {
      setBusyId(null);
    }
  }

  async function quickReject(action: Action) {
    setBusyId(action.id);
    try {
      await api.post(`/actions/${action.id}/reject`, {});
      reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reject failed");
    } finally {
      setBusyId(null);
    }
  }

  const filtered = useMemo(() => {
    if (!actions) return [];
    return statusFilter === "all" ? actions : actions.filter((a) => a.status === statusFilter);
  }, [actions, statusFilter]);

  if (error) return <p className="text-red-600">Error: {error}</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Actions</h1>
          <p className="mt-1 text-sm text-slate-500">
            Recommended operational responses awaiting review, approval, or resolution.
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

      {!actions && <p className="text-slate-500">Loading actions...</p>}

      {actions && (
        <div className="space-y-3">
          {filtered.map((action) => (
            <div key={action.id} className="rounded-lg border border-slate-200 bg-white p-4">
              <div className="mb-2 flex items-center justify-between">
                <StatusBadge status={action.status} />
                <Link href={`/issues/${action.issue_id}`} className="text-xs text-slate-500 hover:underline">
                  View issue →
                </Link>
              </div>
              <p className="text-sm text-slate-700">{action.recommended_text}</p>
              {action.status === "awaiting_approval" && (
                <div className="mt-3 flex gap-2">
                  <button
                    onClick={() => quickApprove(action)}
                    disabled={busyId === action.id}
                    className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => quickReject(action)}
                    disabled={busyId === action.id}
                    className="rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              )}
            </div>
          ))}
          {filtered.length === 0 && <p className="text-slate-400">No actions match this filter.</p>}
        </div>
      )}
    </div>
  );
}

export default function ActionsPage() {
  return <DashboardShell>{(businessId) => <ActionsContent businessId={businessId} />}</DashboardShell>;
}
