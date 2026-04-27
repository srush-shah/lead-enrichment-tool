"use client";

import useSWR from "swr";

type Health = {
  status: string;
  newsapi_used_today?: number;
  gemini_used_today?: number;
};

const NEWS_CAP = 100;
const GEMINI_CAP = 100;
const LOW_THRESHOLD = 0.15;

const fetcher = (url: string) =>
  fetch(url, { cache: "no-store" }).then((r) => r.json() as Promise<Health>);

export function QuotaWarning() {
  const { data } = useSWR<Health>("/api/proxy/health", fetcher, {
    refreshInterval: 30_000,
    revalidateOnFocus: true,
  });

  if (!data || data.status === "down") return null;

  const news = data.newsapi_used_today ?? 0;
  const gemini = data.gemini_used_today ?? 0;
  const lowNews = (NEWS_CAP - news) / NEWS_CAP < LOW_THRESHOLD;
  const lowGemini = (GEMINI_CAP - gemini) / GEMINI_CAP < LOW_THRESHOLD;
  if (!lowNews && !lowGemini) return null;

  const which = [lowNews && "NewsAPI", lowGemini && "Gemini"]
    .filter(Boolean)
    .join(" and ");

  return (
    <div
      role="status"
      className="mb-4 rounded-md border border-amber-500/40 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-400/30 dark:bg-amber-950/30 dark:text-amber-200"
    >
      Heads up — {which} quota is below 15%. Enrichment may use fallbacks
      until the daily reset (UTC midnight).
    </div>
  );
}
