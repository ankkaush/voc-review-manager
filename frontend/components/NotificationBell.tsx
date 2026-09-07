"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { Notification } from "@/lib/types";

const POLL_INTERVAL_MS = 30_000;

function linkFor(notification: Notification): string {
  if (notification.entity_type === "issue") return `/issues/${notification.entity_id}`;
  if (notification.entity_type === "action") return "/actions";
  return "/";
}

export function NotificationBell({ businessId }: { businessId: string }) {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    function load() {
      api
        .get<Notification[]>(`/notifications?business_id=${businessId}&unread_only=true`)
        .then((list) => {
          if (!cancelled) setNotifications(list);
        })
        .catch(() => {
          // Non-critical background poll — leave the last known list on screen.
        });
    }

    load();
    const interval = setInterval(load, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [businessId]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function handleMarkRead(notification: Notification) {
    setNotifications((prev) => prev.filter((n) => n.id !== notification.id));
    try {
      await api.post(`/notifications/${notification.id}/read`);
    } catch {
      // Refetch on next poll if this failed silently.
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100"
        aria-label="Notifications"
      >
        Notifications
        {notifications.length > 0 && (
          <span className="absolute -right-1.5 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold text-white">
            {notifications.length}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-10 mt-2 w-80 rounded-md border border-slate-200 bg-white shadow-lg">
          {notifications.length === 0 ? (
            <p className="px-4 py-3 text-sm text-slate-500">No unread notifications.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-slate-100 overflow-y-auto">
              {notifications.map((notification) => (
                <li key={notification.id} className="px-4 py-3 text-sm">
                  <Link
                    href={linkFor(notification)}
                    onClick={() => {
                      setOpen(false);
                      void handleMarkRead(notification);
                    }}
                    className="block text-slate-700 hover:text-slate-900"
                  >
                    {notification.message}
                  </Link>
                  <button
                    onClick={() => void handleMarkRead(notification)}
                    className="mt-1 text-xs text-slate-400 hover:text-slate-600"
                  >
                    Mark as read
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
