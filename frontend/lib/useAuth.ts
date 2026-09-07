"use client";

import { useEffect, useState } from "react";
import { getToken } from "./api";

export function useRequireAuth(): { ready: boolean } {
  // Must start `false` to match the server render (no localStorage server-side) — a
  // lazy initializer reading the token would hydrate mismatched. The effect below
  // syncs from that external system (localStorage) exactly as the rule's own docs
  // recommend, so the setState here is intentional, not an anti-pattern.
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      window.location.href = "/login";
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setReady(true);
  }, []);

  return { ready };
}
