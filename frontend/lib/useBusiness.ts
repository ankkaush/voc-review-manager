"use client";

import { useEffect, useState } from "react";
import { api } from "./api";
import type { Business } from "./types";

const BUSINESS_KEY = "voc_business_id";

export function useBusiness(): {
  businesses: Business[];
  businessId: string | null;
  setBusinessId: (id: string) => void;
  loading: boolean;
  error: string | null;
} {
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [businessId, setBusinessIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<Business[]>("/businesses")
      .then((list) => {
        setBusinesses(list);
        const stored = window.localStorage.getItem(BUSINESS_KEY);
        const initial = list.find((b) => b.id === stored)?.id ?? list[0]?.id ?? null;
        setBusinessIdState(initial);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load businesses"))
      .finally(() => setLoading(false));
  }, []);

  function setBusinessId(id: string) {
    window.localStorage.setItem(BUSINESS_KEY, id);
    setBusinessIdState(id);
  }

  return { businesses, businessId, setBusinessId, loading, error };
}
