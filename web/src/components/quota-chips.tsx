"use client";

import useSWR from "swr";
import { Badge } from "@/components/ui/badge";

type Health = {
  status: string;
  newsapi_used_today?: number;
  gemini_used_today?: number;
  error?: string;
};

const NEWS_CAP = 100;
const GEMINI_CAP = 100;

const fetcher = (url: string) =>
  fetch(url, { cache: "no-store" }).then((r) => r.json() as Promise<Health>);

function chipVariant(used: number | undefined, cap: number) {
  if (used == null) return "secondary" as const;
  const ratio = used / cap;
  if (ratio >= 0.9) return "destructive" as const;
  if (ratio >= 0.6) return "outline" as const;
  return "secondary" as const;
}

export function QuotaChips() {
  const { data, error } = useSWR<Health>("/api/proxy/health", fetcher, {
    refreshInterval: 30_000,
    revalidateOnFocus: true,
  });

  if (error || data?.status === "down") {
    return (
      <Badge variant="destructive" className="gap-1">
        backend offline
      </Badge>
    );
  }

  const news = data?.newsapi_used_today;
  const gemini = data?.gemini_used_today;

  return (
    <div className="flex items-center gap-2">
      <Badge variant={chipVariant(news, NEWS_CAP)} className="font-mono">
        News {news ?? "—"}/{NEWS_CAP}
      </Badge>
      <Badge variant={chipVariant(gemini, GEMINI_CAP)} className="font-mono">
        Gemini {gemini ?? "—"}/{GEMINI_CAP}
      </Badge>
    </div>
  );
}
