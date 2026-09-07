"use client";

import dynamic from "next/dynamic";

// This dashboard is inherently client-only (JWT in localStorage, no server session) —
// attempting to SSR it produces a hydration mismatch the moment auth state diverges
// from the server's stateless render. `ssr: false` renders nothing on the server and
// mounts fresh on the client, which is the correct behavior here, not a workaround.
export const DashboardShellNoSSR = dynamic(
  () => import("./DashboardShell").then((m) => m.DashboardShell),
  { ssr: false }
);
