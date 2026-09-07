const STATUS_COLORS: Record<string, string> = {
  identified: "bg-slate-100 text-slate-700",
  reviewed: "bg-blue-100 text-blue-700",
  recommended: "bg-indigo-100 text-indigo-700",
  awaiting_approval: "bg-amber-100 text-amber-700",
  approved: "bg-teal-100 text-teal-700",
  action_created: "bg-cyan-100 text-cyan-700",
  resolved: "bg-emerald-100 text-emerald-700",
  monitoring: "bg-purple-100 text-purple-700",
  closed: "bg-slate-200 text-slate-500",
  rejected: "bg-red-100 text-red-700",
  // ProcessingRun statuses
  running: "bg-blue-100 text-blue-700",
  completed: "bg-emerald-100 text-emerald-700",
  completed_with_errors: "bg-amber-100 text-amber-700",
  failed: "bg-red-100 text-red-700",
  // Outcome interpretations
  improved: "bg-emerald-100 text-emerald-700",
  worsened: "bg-red-100 text-red-700",
  no_significant_change: "bg-slate-100 text-slate-600",
  insufficient_data: "bg-slate-100 text-slate-400",
};

const SEVERITY_COLORS: Record<string, string> = {
  high: "bg-red-100 text-red-700",
  medium: "bg-amber-100 text-amber-700",
  low: "bg-slate-100 text-slate-600",
};

const TREND_COLORS: Record<string, string> = {
  emerging: "bg-red-100 text-red-700",
  declining: "bg-emerald-100 text-emerald-700",
  stable: "bg-slate-100 text-slate-600",
  new: "bg-blue-100 text-blue-700",
  insufficient_data: "bg-slate-100 text-slate-400",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_COLORS[status] ?? "bg-slate-100 text-slate-600"}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: string | null }) {
  if (!severity) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEVERITY_COLORS[severity] ?? "bg-slate-100 text-slate-600"}`}>
      {severity}
    </span>
  );
}

export function TrendBadge({ direction, changePct }: { direction: string | null; changePct: number | null }) {
  if (!direction) return <span className="text-xs text-slate-400">—</span>;
  const pctLabel = changePct !== null ? ` ${changePct > 0 ? "+" : ""}${changePct.toFixed(0)}%` : "";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TREND_COLORS[direction] ?? "bg-slate-100 text-slate-600"}`}>
      {direction.replace(/_/g, " ")}
      {pctLabel}
    </span>
  );
}
