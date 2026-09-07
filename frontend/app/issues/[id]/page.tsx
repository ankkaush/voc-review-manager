"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { DashboardShellNoSSR as DashboardShell } from "@/components/DashboardShellClient";
import { SeverityBadge, StatusBadge, TrendBadge } from "@/components/Badge";
import { PriorityBreakdown } from "@/components/PriorityBreakdown";
import { api, ApiError } from "@/lib/api";
import type { Action, IssueEvidenceResponse, Outcome, WorkflowEventItem } from "@/lib/types";

function fmtDate(s: string) {
  return new Date(s).toLocaleString();
}

function ActionButton({
  label,
  onClick,
  variant = "primary",
  disabled,
}: {
  label: string;
  onClick: () => void;
  variant?: "primary" | "danger" | "secondary";
  disabled?: boolean;
}) {
  const styles = {
    primary: "bg-slate-900 text-white hover:bg-slate-800",
    danger: "bg-red-600 text-white hover:bg-red-500",
    secondary: "border border-slate-300 text-slate-700 hover:bg-slate-100",
  }[variant];
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${styles}`}
    >
      {label}
    </button>
  );
}

function IssueDetailContent({ issueId }: { issueId: string }) {
  const [evidence, setEvidence] = useState<IssueEvidenceResponse | null>(null);
  const [audit, setAudit] = useState<WorkflowEventItem[]>([]);
  const [action, setAction] = useState<Action | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [decisionNote, setDecisionNote] = useState("");

  const reload = useCallback(async () => {
    try {
      const [ev, auditTrail, actions] = await Promise.all([
        api.get<IssueEvidenceResponse>(`/issues/${issueId}/evidence`),
        api.get<WorkflowEventItem[]>(`/issues/${issueId}/audit`),
        api.get<Action[]>(`/actions?issue_id=${issueId}`),
      ]);
      setEvidence(ev);
      setAudit(auditTrail);
      const latestAction = actions[0] ?? null;
      setAction(latestAction);

      if (latestAction && ["action_created", "resolved", "monitoring", "closed"].includes(latestAction.status)) {
        try {
          const o = await api.get<Outcome>(`/actions/${latestAction.id}/outcome`);
          setOutcome(o);
        } catch (err) {
          if (!(err instanceof ApiError && err.status === 404)) throw err;
          setOutcome(null);
        }
      } else {
        setOutcome(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load issue");
    }
  }, [issueId]);

  useEffect(() => {
    // `reload` only sets state from inside its async/await body, not synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, [reload]);

  async function runAction(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (error && !evidence) return <p className="text-red-600">Error: {error}</p>;
  if (!evidence) return <p className="text-slate-500">Loading...</p>;

  const { issue, metrics, review_citations, latest_insight } = evidence;
  const status = issue.status;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">{issue.title}</h1>
        <p className="mt-1 text-sm text-slate-500">{issue.description}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <StatusBadge status={status} />
          <SeverityBadge severity={issue.severity} />
          <TrendBadge direction={issue.trend_direction} changePct={issue.trend_change_pct} />
          {issue.priority_score !== null && (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
              priority {issue.priority_score.toFixed(2)}
            </span>
          )}
        </div>
      </div>

      {error && <p className="text-sm text-red-600">Error: {error}</p>}

      {/* Workflow actions */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Workflow</h2>
        <div className="flex flex-wrap items-center gap-2">
          {status === "identified" && (
            <>
              <ActionButton label="Mark reviewed" disabled={busy} onClick={() => runAction(() => api.post(`/issues/${issueId}/review`))} />
              <ActionButton
                label="Dismiss"
                variant="danger"
                disabled={busy}
                onClick={() => runAction(() => api.post(`/issues/${issueId}/dismiss`, { reason: decisionNote || null }))}
              />
            </>
          )}

          {status === "reviewed" && (
            <>
              <ActionButton
                label="Recommend action (uses 1 AI call)"
                disabled={busy}
                onClick={() => {
                  if (window.confirm("This calls the configured AI provider once to draft a recommendation. Continue?")) {
                    runAction(() => api.post(`/issues/${issueId}/actions/recommend`));
                  }
                }}
              />
              <ActionButton
                label="Dismiss"
                variant="danger"
                disabled={busy}
                onClick={() => runAction(() => api.post(`/issues/${issueId}/dismiss`, { reason: decisionNote || null }))}
              />
            </>
          )}

          {status === "resolved" && (
            <>
              <ActionButton label="Move to monitoring" disabled={busy} onClick={() => runAction(() => api.post(`/issues/${issueId}/monitor`))} />
              {action && (
                <ActionButton
                  label="Evaluate outcome"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => runAction(() => api.post(`/actions/${action.id}/evaluate-outcome`))}
                />
              )}
            </>
          )}

          {status === "monitoring" && (
            <>
              <ActionButton label="Close issue" disabled={busy} onClick={() => runAction(() => api.post(`/issues/${issueId}/close`))} />
              {action && (
                <ActionButton
                  label="Re-evaluate outcome"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => runAction(() => api.post(`/actions/${action.id}/evaluate-outcome`))}
                />
              )}
            </>
          )}

          {(status === "identified" || status === "reviewed") && (
            <input
              type="text"
              placeholder="Optional dismiss reason"
              value={decisionNote}
              onChange={(e) => setDecisionNote(e.target.value)}
              className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
            />
          )}

          {["closed", "rejected"].includes(status) && (
            <span className="text-sm text-slate-400">This issue is in a terminal state.</span>
          )}
        </div>
      </div>

      {/* Action panel */}
      {action && (
        <div className="rounded-lg border border-slate-200 bg-white p-5">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-700">Recommended action</h2>
            <StatusBadge status={action.status} />
          </div>
          <p className="mb-4 text-sm text-slate-700">{action.recommended_text}</p>

          <div className="flex flex-wrap items-center gap-2">
            {action.status === "recommended" && (
              <ActionButton
                label="Submit for approval"
                disabled={busy}
                onClick={() => runAction(() => api.post(`/actions/${action.id}/submit-for-approval`))}
              />
            )}
            {action.status === "awaiting_approval" && (
              <>
                <input
                  type="text"
                  placeholder="Decision note (optional)"
                  value={decisionNote}
                  onChange={(e) => setDecisionNote(e.target.value)}
                  className="rounded-md border border-slate-300 px-2 py-1.5 text-sm"
                />
                <ActionButton
                  label="Approve"
                  disabled={busy}
                  onClick={() => runAction(() => api.post(`/actions/${action.id}/approve`, { decision_note: decisionNote || null }))}
                />
                <ActionButton
                  label="Reject"
                  variant="danger"
                  disabled={busy}
                  onClick={() => runAction(() => api.post(`/actions/${action.id}/reject`, { decision_note: decisionNote || null }))}
                />
              </>
            )}
            {action.status === "action_created" && (
              <ActionButton label="Mark resolved" disabled={busy} onClick={() => runAction(() => api.post(`/actions/${action.id}/resolve`))} />
            )}
          </div>

          {outcome && (
            <div className="mt-4 border-t border-slate-100 pt-4">
              <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">Outcome</h3>
              <p className="text-sm text-slate-700">
                Before: <strong>{outcome.before_negative_count}</strong> negative mentions (
                {outcome.before_period_start} to {outcome.before_period_end})
                {outcome.after_negative_count !== null && (
                  <>
                    {" "}
                    → After: <strong>{outcome.after_negative_count}</strong> ({outcome.after_period_start} to{" "}
                    {outcome.after_period_end})
                  </>
                )}
              </p>
              <p className="mt-1 text-sm">
                <span className="font-medium text-slate-700">Verdict: </span>
                <StatusBadge status={outcome.interpretation} />
                {outcome.delta_pct !== null && (
                  <span className="ml-2 text-slate-500">{outcome.delta_pct.toFixed(0)}% change</span>
                )}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Insight */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">Insight</h2>
          <ActionButton
            label={latest_insight ? "Regenerate insight (uses 1 AI call)" : "Generate insight (uses 1 AI call)"}
            variant="secondary"
            disabled={busy}
            onClick={() => {
              if (window.confirm("This calls the configured AI provider once to synthesize an insight. Continue?")) {
                runAction(() => api.post(`/issues/${issueId}/insight`));
              }
            }}
          />
        </div>
        {latest_insight ? (
          <div>
            <p className="text-sm text-slate-700">{latest_insight.text}</p>
            <p className="mt-2 text-xs text-slate-400">
              {latest_insight.generation_method === "llm_synthesis" ? "AI-generated" : "Deterministic template"} ·{" "}
              {fmtDate(latest_insight.created_at)}
            </p>
          </div>
        ) : (
          <p className="text-sm text-slate-400">No insight generated yet.</p>
        )}
      </div>

      {/* Priority breakdown */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Priority breakdown</h2>
        <PriorityBreakdown breakdown={issue.priority_score_breakdown} />
      </div>

      {/* Evidence */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">
          Evidence <span className="font-normal text-slate-400">— why is this flagged?</span>
        </h2>
        <table className="mb-4 w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500">
            <tr>
              <th className="py-1 pr-4">Week</th>
              <th className="py-1 pr-4">Mentions</th>
              <th className="py-1 pr-4">Negative</th>
              <th className="py-1 pr-4">Positive</th>
              <th className="py-1">Avg rating</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.aggregate_period_metric_id} className="border-t border-slate-100">
                <td className="py-1.5 pr-4 text-slate-700">
                  {m.period_start} – {m.period_end}
                </td>
                <td className="py-1.5 pr-4 text-slate-500">{m.mention_count}</td>
                <td className="py-1.5 pr-4 font-medium text-red-600">{m.negative_count}</td>
                <td className="py-1.5 pr-4 text-emerald-600">{m.positive_count}</td>
                <td className="py-1.5 text-slate-500">{m.avg_rating?.toFixed(1) ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 className="mb-2 text-xs font-semibold uppercase text-slate-500">
          Representative reviews ({review_citations.length})
        </h3>
        <ul className="space-y-2">
          {review_citations.map((r) => (
            <li key={r.review_id} className="rounded-md bg-slate-50 p-3 text-sm text-slate-700">
              <p>&ldquo;{r.text}&rdquo;</p>
              <p className="mt-1 text-xs text-slate-400">
                {r.rating ? `${r.rating}★` : "no rating"} · {fmtDate(r.submitted_at)}
              </p>
            </li>
          ))}
        </ul>
      </div>

      {/* Audit trail */}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-700">Audit trail</h2>
        <ul className="space-y-1.5 text-sm">
          {audit.map((e, i) => (
            <li key={i} className="flex items-center gap-2 text-slate-600">
              <span className="w-16 shrink-0 text-xs uppercase text-slate-400">{e.entity_type}</span>
              <span>
                {e.from_state ?? "(created)"} → <strong className="text-slate-800">{e.to_state}</strong>
              </span>
              <span className="text-xs text-slate-400">by {e.actor}</span>
              <span className="text-xs text-slate-400">{fmtDate(e.created_at)}</span>
              {e.reason && <span className="text-xs italic text-slate-400">&ldquo;{e.reason}&rdquo;</span>}
            </li>
          ))}
          {audit.length === 0 && <li className="text-slate-400">No events yet.</li>}
        </ul>
      </div>
    </div>
  );
}

function IssueDetailPageInner() {
  const params = useParams<{ id: string }>();
  return <IssueDetailContent issueId={params.id} />;
}

export default function IssueDetailPage() {
  return <DashboardShell>{() => <IssueDetailPageInner />}</DashboardShell>;
}
