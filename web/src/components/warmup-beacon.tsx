"use client";

import { useEffect } from "react";

export function WarmupBeacon() {
  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/proxy/health", { cache: "no-store", signal: ctrl.signal }).catch(
      () => {},
    );
    return () => ctrl.abort();
  }, []);
  return null;
}
