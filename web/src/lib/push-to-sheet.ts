import { toast } from "sonner";

export type PushResult = {
  written: number;
  sheet?: string | null;
  skipped?: number[];
};

const SHEET_URL = process.env.NEXT_PUBLIC_PILOT_SHEET_URL ?? "";

/**
 * POST a list of cache lead-ids to the Apps Script-fronted Sheet.
 * Handles its own toasting so call sites stay short.
 *
 * Returns the server response on success; null on failure (a toast was
 * already shown). Callers can use the return value to e.g. open the
 * sheet in a new tab after a successful push.
 */
export async function pushLeadsToSheet(
  leadIds: number[],
  opts: { sheetName?: string } = {},
): Promise<PushResult | null> {
  const ids = leadIds.filter((n) => Number.isFinite(n));
  if (ids.length === 0) {
    toast.error("Nothing to push — no enriched leads selected");
    return null;
  }
  try {
    const res = await fetch("/api/proxy/leads/push-to-sheet", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lead_ids: ids, sheet_name: opts.sheetName }),
    });
    if (res.status === 401) {
      toast.error("Session expired — please sign in again");
      window.location.href = "/login";
      return null;
    }
    const text = await res.text();
    let body: { written?: number; sheet?: string; skipped?: number[]; detail?: string } = {};
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = {};
    }
    if (!res.ok) {
      toast.error(`Push to Sheet failed (${res.status}) — ${body.detail || text.slice(0, 120) || "unknown error"}`);
      return null;
    }
    const written = body.written ?? 0;
    const skipped = body.skipped ?? [];
    const tab = body.sheet ?? "Web App Output";
    if (SHEET_URL) {
      toast.success(`Pushed ${written} row${written === 1 ? "" : "s"} to "${tab}"`, {
        action: { label: "Open sheet", onClick: () => window.open(SHEET_URL, "_blank", "noopener") },
      });
    } else {
      toast.success(
        `Pushed ${written} row${written === 1 ? "" : "s"} to "${tab}"` +
          (skipped.length ? ` · ${skipped.length} skipped` : ""),
      );
    }
    return { written, sheet: tab, skipped };
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "Network error");
    return null;
  }
}

export const PILOT_SHEET_URL = SHEET_URL;
