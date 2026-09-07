interface Factor {
  raw: unknown;
  score: number;
  weight: number;
  contribution: number;
  direction?: string;
}

export function PriorityBreakdown({ breakdown }: { breakdown: Record<string, unknown> | null }) {
  if (!breakdown || !breakdown.factors) {
    return <p className="text-sm text-slate-400">Not yet computed — run priority recompute first.</p>;
  }
  const factors = breakdown.factors as Record<string, Factor>;

  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs uppercase text-slate-500">
        <tr>
          <th className="py-1 pr-4">Factor</th>
          <th className="py-1 pr-4">Value</th>
          <th className="py-1 pr-4">Score</th>
          <th className="py-1 pr-4">Weight</th>
          <th className="py-1">Contribution</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(factors).map(([name, f]) => (
          <tr key={name} className="border-t border-slate-100">
            <td className="py-1.5 pr-4 font-medium capitalize text-slate-700">{name.replace(/_/g, " ")}</td>
            <td className="py-1.5 pr-4 text-slate-500">{String(f.raw ?? "—")}</td>
            <td className="py-1.5 pr-4 text-slate-500">{f.score.toFixed(2)}</td>
            <td className="py-1.5 pr-4 text-slate-500">{f.weight.toFixed(2)}</td>
            <td className="py-1.5 font-medium text-slate-700">{f.contribution.toFixed(3)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
