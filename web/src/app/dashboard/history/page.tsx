"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowLeftIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  HistoryIcon,
  ListIcon,
} from "lucide-react";
import { toast } from "sonner";
import useSWR from "swr";
import { LeadResultCard } from "@/components/lead-result-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { EnrichedLead, LeadInput, Tier } from "@/lib/types";

const PAGE_SIZE = 20;

const TIER_VARIANT: Record<Tier, "default" | "secondary" | "outline" | "destructive"> = {
  A: "default",
  B: "secondary",
  C: "outline",
  D: "outline",
  Skipped: "destructive",
};

type LeadSummary = {
  id: number;
  tier: Tier;
  score: number | null;
  created_at: string;
  input: LeadInput;
};

type LeadsListResponse = {
  leads: LeadSummary[];
  total: number;
  limit: number;
  offset: number;
};

async function fetcher<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: "no-store" });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
}

function parseUtc(s: string): Date {
  // SQLite's CURRENT_TIMESTAMP returns e.g. "2026-04-27 18:21:33" with no
  // timezone marker but is UTC. Without this fix, Safari parses it as local.
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) return new Date(s);
  return new Date(s.replace(" ", "T") + "Z");
}

function formatWhen(s: string): string {
  return parseUtc(s).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function HistoryPage() {
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const listKey = `/api/proxy/leads?limit=${PAGE_SIZE}&offset=${offset}`;
  const {
    data: list,
    isLoading: listLoading,
    mutate: mutateList,
  } = useSWR<LeadsListResponse>(listKey, fetcher, {
    onError: (err: Error) => {
      if (err.message !== "unauthorized") toast.error("Failed to load history");
    },
  });

  const detailKey = selectedId != null ? `/api/proxy/leads/${selectedId}` : null;
  const {
    data: detail,
    isLoading: detailLoading,
    mutate: mutateDetail,
  } = useSWR<EnrichedLead>(detailKey, fetcher, {
    onError: (err: Error) => {
      if (err.message !== "unauthorized") toast.error("Failed to open lead");
      setSelectedId(null);
    },
  });

  const total = list?.total ?? 0;
  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + PAGE_SIZE, total);
  const hasPrev = offset > 0;
  const hasNext = offset + PAGE_SIZE < total;

  if (selectedId != null) {
    const leadForCard = detail ? { ...detail, id: selectedId } : null;
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setSelectedId(null)}
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
          >
            <ArrowLeftIcon className="size-3.5" />
            Back to history
          </button>
        </div>
        {leadForCard ? (
          <LeadResultCard
            lead={leadForCard}
            onUpdate={(next) => {
              const { id: _id, ...rest } = next;
              void _id;
              void mutateDetail(rest as EnrichedLead, { revalidate: false });
              void mutateList(
                (prev) =>
                  prev
                    ? {
                        ...prev,
                        leads: prev.leads.map((l) =>
                          l.id === selectedId
                            ? { ...l, tier: next.tier, score: next.score }
                            : l,
                        ),
                      }
                    : prev,
                { revalidate: false },
              );
            }}
          />
        ) : (
          <Card>
            <CardContent className="text-muted-foreground flex h-64 items-center justify-center text-sm">
              {detailLoading ? "Loading lead…" : "Lead not found."}
            </CardContent>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link
          href="/dashboard"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
        >
          <ArrowLeftIcon className="size-3.5" />
          Dashboard
        </Link>
        <h1 className="text-xl font-semibold tracking-tight">History</h1>
      </div>

      <Card>
        <CardHeader className="border-b pb-3">
          <div className="flex items-center justify-between gap-3">
            <div>
              <CardTitle className="text-base">Past enrichments</CardTitle>
              <CardDescription>
                Scoped to your account. Click a row to re-open or regenerate.
              </CardDescription>
            </div>
            <Badge variant="outline" className="font-mono">
              <HistoryIcon className="mr-1 size-3" />
              {total} total
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {listLoading && !list ? (
            <div className="text-muted-foreground flex h-64 items-center justify-center text-sm">
              Loading history…
            </div>
          ) : total === 0 ? (
            <EmptyHistory />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Tier</TableHead>
                  <TableHead>Score</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Company</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>When</TableHead>
                  <TableHead className="w-12 text-right">Open</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list?.leads.map((row) => (
                  <TableRow
                    key={row.id}
                    onClick={() => setSelectedId(row.id)}
                    className="cursor-pointer"
                  >
                    <TableCell>
                      <Badge variant={TIER_VARIANT[row.tier]} className="font-mono">
                        {row.tier}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono tabular-nums">
                      {row.score != null ? Math.round(row.score) : "—"}
                    </TableCell>
                    <TableCell>{row.input.name}</TableCell>
                    <TableCell className="text-muted-foreground">{row.input.company}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {row.input.city}, {row.input.state}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {formatWhen(row.created_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedId(row.id);
                        }}
                      >
                        Open
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {total > 0 && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            Showing {pageStart}–{pageEnd} of {total}
          </span>
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              disabled={!hasPrev || listLoading}
            >
              <ChevronLeftIcon /> Prev
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setOffset(offset + PAGE_SIZE)}
              disabled={!hasNext || listLoading}
            >
              Next <ChevronRightIcon />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function EmptyHistory() {
  return (
    <div className="text-muted-foreground flex h-64 flex-col items-center justify-center gap-2 text-center text-sm">
      <ListIcon className="size-6 opacity-40" />
      <p>
        No leads yet. Enrich a single lead or run a batch — they&apos;ll show up here
        scoped to your account.
      </p>
      <div className="mt-2 flex gap-2">
        <Link href="/dashboard/new">
          <Button size="sm" variant="outline">
            New lead
          </Button>
        </Link>
        <Link href="/dashboard/bulk">
          <Button size="sm" variant="outline">
            Bulk upload
          </Button>
        </Link>
      </div>
    </div>
  );
}
