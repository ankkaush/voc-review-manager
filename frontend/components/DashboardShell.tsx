"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clearToken } from "@/lib/api";
import { useRequireAuth } from "@/lib/useAuth";
import { useBusiness } from "@/lib/useBusiness";
import { NotificationBell } from "./NotificationBell";
import type { ReactNode } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/customer-experience", label: "Customer Experience" },
  { href: "/issues", label: "Issues" },
  { href: "/actions", label: "Actions" },
  { href: "/system-health", label: "System Health" },
];

export function DashboardShell({ children }: { children: (businessId: string) => ReactNode }) {
  const { ready } = useRequireAuth();
  const { businesses, businessId, setBusinessId, loading, error } = useBusiness();
  const pathname = usePathname();

  if (!ready) return null;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-8">
            <span className="text-lg font-semibold">Voice of Customer</span>
            <nav className="flex gap-1">
              {NAV_ITEMS.map((item) => {
                const active = pathname === item.href;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`rounded-md px-3 py-1.5 text-sm font-medium ${
                      active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-3">
            {businesses.length > 1 && (
              <select
                className="rounded-md border border-slate-300 px-2 py-1 text-sm"
                value={businessId ?? ""}
                onChange={(e) => setBusinessId(e.target.value)}
              >
                {businesses.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </select>
            )}
            {businessId && businesses.length === 1 && (
              <span className="text-sm text-slate-500">{businesses[0].name}</span>
            )}
            {businessId && <NotificationBell businessId={businessId} />}
            <button
              onClick={() => {
                clearToken();
                window.location.href = "/login";
              }}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        {loading && <p className="text-slate-500">Loading...</p>}
        {error && <p className="text-red-600">Error: {error}</p>}
        {/* Keying on businessId remounts page content on business switch, so each
            page's local state starts fresh instead of needing a manual reset inside
            its data-fetch effect. */}
        {!loading && !error && businessId && <div key={businessId}>{children(businessId)}</div>}
        {!loading && !error && !businessId && (
          <p className="text-slate-500">No business found. Run the dataset loader script first.</p>
        )}
      </main>
    </div>
  );
}
