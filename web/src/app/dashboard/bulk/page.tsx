"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from "react";
import Link from "next/link";
import Papa from "papaparse";
import {
  ArrowLeftIcon,
  ChevronsUpDownIcon,
  ClipboardCopyIcon,
  DownloadIcon,
  FileSpreadsheetIcon,
  SparklesIcon,
  TrashIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import { toast } from "sonner";
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
import { buildCsv, buildTsv, downloadFile } from "@/lib/csv-export";
import { readSse } from "@/lib/sse";
import type { EnrichedLead, LeadInput, Tier } from "@/lib/types";

const REQUIRED_FIELDS = [
  "name",
  "email",
  "company",
  "property_address",
  "city",
  "state",
] as const;

const MAX_ROWS = 50;

const TIER_VARIANT: Record<Tier, "default" | "secondary" | "outline" | "destructive"> = {
  A: "default",
  B: "secondary",
  C: "outline",
  D: "outline",
  Skipped: "destructive",
};

const TIER_RANK: Record<Tier, number> = { A: 5, B: 4, C: 3, D: 2, Skipped: 1 };

type SortKey = "name" | "company" | "tier" | "score" | "msa";
type SortDir = "asc" | "desc";

type RowError = { lead: LeadInput; message: string };

type BulkSnapshot = {
  filename: string | null;
  rows: LeadInput[];
  results: EnrichedLead[];
  errors: RowError[];
  startedAt: number;
  finishedAt: number | null;
};

const STORAGE_KEY = "bulk:lastUpload";

function readSnapshot(): BulkSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as BulkSnapshot;
  } catch {
    return null;
  }
}

function writeSnapshot(snap: BulkSnapshot): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(snap));
  } catch {
    // Quota or disabled storage — silently skip; rehydrate is a nice-to-have.
  }
}

function clearSnapshot(): void {
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

export default function BulkUploadPage() {
  const [filename, setFilename] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [rows, setRows] = useState<LeadInput[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [results, setResults] = useState<EnrichedLead[]>([]);
  const [errors, setErrors] = useState<RowError[]>([]);
  const [sortKey, setSortKey] = useState<SortKey>("score");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [dragOver, setDragOver] = useState(false);
  const [interrupted, setInterrupted] = useState(false);
  const [rehydrated, setRehydrated] = useState(false);
  const startedAtRef = useRef<number | null>(null);
  const finishedAtRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Rehydrate from localStorage on mount. Visible state (rows/results/errors)
  // survives a navigation away; the in-flight stream itself does not.
  useEffect(() => {
    const snap = readSnapshot();
    if (snap) {
      setFilename(snap.filename);
      setRows(snap.rows);
      setResults(snap.results);
      setErrors(snap.errors);
      startedAtRef.current = snap.startedAt;
      finishedAtRef.current = snap.finishedAt;
      if (snap.finishedAt == null && (snap.results.length > 0 || snap.errors.length > 0)) {
        setInterrupted(true);
      }
    }
    setRehydrated(true);
  }, []);

  // Persist after every state change once rehydration is settled.
  useEffect(() => {
    if (!rehydrated) return;
    if (!filename && rows.length === 0 && results.length === 0 && errors.length === 0) {
      clearSnapshot();
      return;
    }
    writeSnapshot({
      filename,
      rows,
      results,
      errors,
      startedAt: startedAtRef.current ?? Date.now(),
      finishedAt: finishedAtRef.current,
    });
  }, [rehydrated, filename, rows, results, errors, streaming]);

  const total = rows.length;
  const completed = results.length + errors.length;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;

  const sortedResults = useMemo(() => {
    const copy = [...results];
    copy.sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      switch (sortKey) {
        case "name":
          return a.input.name.localeCompare(b.input.name) * dir;
        case "company":
          return a.input.company.localeCompare(b.input.company) * dir;
        case "msa":
          return (a.msa ?? "").localeCompare(b.msa ?? "") * dir;
        case "tier":
          return (TIER_RANK[a.tier] - TIER_RANK[b.tier]) * dir;
        case "score":
          return ((a.score ?? -1) - (b.score ?? -1)) * dir;
      }
    });
    return copy;
  }, [results, sortKey, sortDir]);

  const handleFile = useCallback((file: File) => {
    setFilename(file.name);
    setParseError(null);
    setRows([]);
    setResults([]);
    setErrors([]);
    setInterrupted(false);
    startedAtRef.current = null;
    finishedAtRef.current = null;

    Papa.parse<Record<string, string>>(file, {
      header: true,
      skipEmptyLines: true,
      transformHeader: (h) => h.trim(),
      complete: (res) => {
        const headers = res.meta.fields ?? [];
        const missing = REQUIRED_FIELDS.filter((f) => !headers.includes(f));
        if (missing.length > 0) {
          setParseError(
            `Missing required column${missing.length > 1 ? "s" : ""}: ${missing.join(", ")}. ` +
              `Required: ${REQUIRED_FIELDS.join(", ")}.`,
          );
          return;
        }
        const parsed: LeadInput[] = [];
        for (const row of res.data) {
          const lead: LeadInput = {
            name: (row.name ?? "").trim(),
            email: (row.email ?? "").trim(),
            company: (row.company ?? "").trim(),
            property_address: (row.property_address ?? "").trim(),
            city: (row.city ?? "").trim(),
            state: (row.state ?? "").trim().toUpperCase(),
            country: (row.country ?? "USA").trim() || "USA",
          };
          if (REQUIRED_FIELDS.every((k) => lead[k])) parsed.push(lead);
        }
        if (parsed.length === 0) {
          setParseError("No valid rows found. Each row needs name, email, company, address, city, state.");
          return;
        }
        if (parsed.length > MAX_ROWS) {
          setParseError(`File has ${parsed.length} rows. Cap is ${MAX_ROWS} for the demo.`);
          return;
        }
        setRows(parsed);
      },
      error: (err) => setParseError(`CSV parse failed: ${err.message}`),
    });
  }, []);

  function onFileInput(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  function reset() {
    setFilename(null);
    setParseError(null);
    setRows([]);
    setResults([]);
    setErrors([]);
    setInterrupted(false);
    startedAtRef.current = null;
    finishedAtRef.current = null;
    clearSnapshot();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function runBatch() {
    if (rows.length === 0 || streaming) return;
    setStreaming(true);
    setResults([]);
    setErrors([]);
    setInterrupted(false);
    startedAtRef.current = Date.now();
    finishedAtRef.current = null;
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch("/api/proxy/enrich/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ leads: rows }),
        signal: controller.signal,
      });
      if (res.status === 401) {
        toast.error("Session expired — please sign in again");
        window.location.href = "/login";
        return;
      }
      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => "");
        toast.error(`Stream failed (${res.status}) — ${text.slice(0, 120)}`);
        return;
      }

      let received = 0;
      for await (const evt of readSse(res.body, controller.signal)) {
        if (evt.event === "done") break;
        if (evt.event !== "lead") continue;
        try {
          const lead = JSON.parse(evt.data) as EnrichedLead;
          setResults((prev) => [...prev, lead]);
        } catch (err) {
          const idx = received < rows.length ? received : rows.length - 1;
          setErrors((prev) => [
            ...prev,
            {
              lead: rows[idx],
              message: err instanceof Error ? err.message : "Bad event payload",
            },
          ]);
        }
        received += 1;
      }
      finishedAtRef.current = Date.now();
      toast.success(`Enriched ${received} of ${rows.length} leads`);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        toast.message("Run cancelled");
      } else {
        toast.error(err instanceof Error ? err.message : "Stream error");
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function cancel() {
    abortRef.current?.abort();
  }

  function exportCsv() {
    if (results.length === 0) return;
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    downloadFile(buildCsv(results), `enriched-leads-${stamp}.csv`, "text/csv");
    toast.success("CSV downloaded");
  }

  async function copyTsv() {
    if (results.length === 0) return;
    try {
      await navigator.clipboard.writeText(buildTsv(results));
      toast.success("TSV copied — paste into Sheets or Excel");
    } catch {
      toast.error("Copy failed — browser blocked clipboard");
    }
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "name" || key === "company" || key === "msa" ? "asc" : "desc");
    }
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
        <h1 className="text-xl font-semibold tracking-tight">Bulk upload</h1>
      </div>

      {interrupted && (
        <div className="flex items-start justify-between gap-3 rounded-md border border-amber-500/40 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-400/30 dark:bg-amber-950/30 dark:text-amber-200">
          <div>
            Showing partial results from a previous upload that didn&apos;t finish.
            The in-flight stream stopped when you navigated away — to keep going,
            re-upload the remaining leads.
          </div>
          <Button
            size="xs"
            variant="ghost"
            onClick={() => setInterrupted(false)}
            className="text-amber-900 hover:text-amber-950 dark:text-amber-200"
          >
            Dismiss
          </Button>
        </div>
      )}

      <Card>
        <CardHeader className="border-b pb-3">
          <CardTitle className="text-base">CSV input</CardTitle>
          <CardDescription>
            Same schema as <code className="text-xs">sample_data/leads_input.csv</code>.
            Required columns: {REQUIRED_FIELDS.join(", ")}. Country defaults to USA.
            Capped at {MAX_ROWS} rows.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {!filename ? (
            <div
              onDragEnter={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragOver={(e) => e.preventDefault()}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              className={
                "rounded-lg border-2 border-dashed transition-colors " +
                (dragOver
                  ? "border-primary bg-primary/5"
                  : "border-muted-foreground/30 hover:border-muted-foreground/50")
              }
            >
              <label className="flex cursor-pointer flex-col items-center justify-center gap-2 px-6 py-12 text-center">
                <UploadIcon className="size-6 opacity-50" />
                <span className="text-sm">
                  Drop a CSV here or <span className="text-primary underline">browse</span>
                </span>
                <span className="text-xs text-muted-foreground">
                  .csv, header row required
                </span>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,text/csv"
                  className="sr-only"
                  onChange={onFileInput}
                />
              </label>
            </div>
          ) : (
            <div className="flex items-center justify-between gap-3 rounded-md border bg-muted/30 px-3 py-2 text-sm">
              <div className="flex items-center gap-2 truncate">
                <FileSpreadsheetIcon className="size-4 text-muted-foreground" />
                <span className="truncate font-medium">{filename}</span>
                {rows.length > 0 && (
                  <Badge variant="outline" className="font-mono">
                    {rows.length} row{rows.length === 1 ? "" : "s"}
                  </Badge>
                )}
              </div>
              <Button variant="ghost" size="sm" onClick={reset} disabled={streaming}>
                <TrashIcon /> Clear
              </Button>
            </div>
          )}

          {parseError && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              {parseError}
            </div>
          )}

          {rows.length > 0 && !parseError && (
            <div className="flex items-center justify-between gap-3 pt-1">
              <div className="text-xs text-muted-foreground">
                {streaming
                  ? `${completed} of ${total} done`
                  : completed === total && total > 0
                    ? `Finished — ${results.length} enriched, ${errors.length} errored`
                    : `Ready to enrich ${total} lead${total === 1 ? "" : "s"}`}
              </div>
              <div className="flex items-center gap-2">
                {streaming ? (
                  <Button variant="ghost" size="sm" onClick={cancel}>
                    <XIcon /> Cancel
                  </Button>
                ) : (
                  <Button onClick={runBatch} disabled={rows.length === 0}>
                    <SparklesIcon /> Run batch
                  </Button>
                )}
              </div>
            </div>
          )}

          {(streaming || (completed > 0 && total > 0)) && (
            <div className="space-y-1">
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${progressPct}%` }}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {(results.length > 0 || errors.length > 0) && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between gap-3 border-b pb-3">
            <div>
              <CardTitle className="text-base">Results</CardTitle>
              <CardDescription>
                {results.length} enriched
                {errors.length > 0 ? ` · ${errors.length} errored` : ""}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={copyTsv} disabled={results.length === 0}>
                <ClipboardCopyIcon /> Copy as TSV
              </Button>
              <Button size="sm" onClick={exportCsv} disabled={results.length === 0}>
                <DownloadIcon /> Export CSV
              </Button>
            </div>
          </CardHeader>
          <CardContent className="px-0 py-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <SortableHeader label="Name" k="name" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <SortableHeader label="Company" k="company" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <SortableHeader label="Tier" k="tier" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <SortableHeader label="Score" k="score" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <SortableHeader label="MSA" k="msa" sortKey={sortKey} sortDir={sortDir} onClick={toggleSort} />
                  <TableHead>Why now</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedResults.map((lead, idx) => (
                  <TableRow key={`${lead.input.email}-${idx}`}>
                    <TableCell className="font-medium">{lead.input.name}</TableCell>
                    <TableCell>{lead.input.company}</TableCell>
                    <TableCell>
                      <Badge variant={TIER_VARIANT[lead.tier]} className="font-mono">
                        {lead.tier}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono tabular-nums">
                      {lead.score != null ? Math.round(lead.score) : "—"}
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {lead.msa ?? "—"}
                      {lead.in_top25_msa ? " · top-25" : ""}
                    </TableCell>
                    <TableCell className="max-w-[320px] truncate text-xs">
                      {lead.skipped_reason ? (
                        <span className="text-destructive">Skipped: {lead.skipped_reason}</span>
                      ) : (
                        (lead.brief?.why_now ?? "—")
                      )}
                    </TableCell>
                  </TableRow>
                ))}
                {errors.map((err, idx) => (
                  <TableRow key={`err-${idx}`}>
                    <TableCell className="font-medium">{err.lead.name}</TableCell>
                    <TableCell>{err.lead.company}</TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-1.5 text-destructive">
                        <span className="size-1.5 rounded-full bg-destructive" />
                        Error
                      </span>
                    </TableCell>
                    <TableCell className="font-mono tabular-nums">—</TableCell>
                    <TableCell className="text-xs text-muted-foreground">—</TableCell>
                    <TableCell className="max-w-[320px] truncate text-xs text-destructive">
                      {err.message}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SortableHeader({
  label,
  k,
  sortKey,
  sortDir,
  onClick,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onClick: (k: SortKey) => void;
}) {
  const active = sortKey === k;
  return (
    <TableHead>
      <button
        type="button"
        onClick={() => onClick(k)}
        className="inline-flex items-center gap-1 text-left text-foreground hover:text-primary"
      >
        {label}
        <ChevronsUpDownIcon
          className={"size-3 " + (active ? "opacity-100 text-primary" : "opacity-40")}
        />
        {active && <span className="sr-only">{sortDir}</span>}
      </button>
    </TableHead>
  );
}
