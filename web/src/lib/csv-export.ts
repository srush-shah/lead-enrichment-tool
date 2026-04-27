import type { EnrichedLead } from "@/lib/types";

export const EXPORT_COLUMNS = [
  "name",
  "email",
  "company",
  "property_address",
  "city",
  "state",
  "country",
  "tier",
  "score",
  "mps",
  "pre_score",
  "market_fit",
  "company_fit",
  "timing",
  "geographic",
  "msa",
  "in_top25_msa",
  "corporate_domain",
  "skipped_reason",
  "why_now",
  "why_now_source",
  "talking_point",
  "objection_preempt",
  "draft_email_subject",
  "draft_email_body",
  "renter_pct",
  "pct_5plus_units",
  "median_gross_rent",
  "walkscore",
  "population",
  "zip_code",
  "has_wikipedia",
  "news_article_count",
  "news_skipped_reason",
  "evidence_links",
] as const;

type RawExtras = {
  census?: {
    renter_occupied_pct?: number | null;
    pct_5plus_units?: number | null;
    median_gross_rent?: number | null;
    population?: number | null;
  };
  walk?: { walkscore?: number | null };
  geo?: { zip_code?: string | null };
  news?: { articles?: unknown[]; skipped_reason?: string | null };
};

export function flattenLead(lead: EnrichedLead): Record<string, unknown> {
  const sub = lead.sub_scores;
  const brief = lead.brief;
  const extras = lead as EnrichedLead & RawExtras;
  const articles = extras.news?.articles ?? lead.news?.articles ?? [];
  return {
    name: lead.input.name,
    email: lead.input.email,
    company: lead.input.company,
    property_address: lead.input.property_address,
    city: lead.input.city,
    state: lead.input.state,
    country: lead.input.country,
    tier: lead.tier,
    score: lead.score,
    mps: sub?.mps ?? null,
    pre_score: sub?.pre_score ?? null,
    market_fit: sub?.market_fit ?? null,
    company_fit: sub?.company_fit ?? null,
    timing: sub?.timing ?? null,
    geographic: sub?.geographic ?? null,
    msa: lead.msa,
    in_top25_msa: lead.in_top25_msa,
    corporate_domain: lead.corporate_domain,
    skipped_reason: lead.skipped_reason,
    why_now: brief?.why_now ?? null,
    why_now_source: brief?.why_now_source ?? null,
    talking_point: brief?.talking_point ?? null,
    objection_preempt: brief?.objection_preempt ?? null,
    draft_email_subject: lead.draft_email_subject,
    draft_email_body: lead.draft_email_body,
    renter_pct: extras.census?.renter_occupied_pct ?? null,
    pct_5plus_units: extras.census?.pct_5plus_units ?? null,
    median_gross_rent: extras.census?.median_gross_rent ?? null,
    walkscore: extras.walk?.walkscore ?? null,
    population: extras.census?.population ?? null,
    zip_code: extras.geo?.zip_code ?? null,
    has_wikipedia: lead.company?.has_wikipedia ?? false,
    news_article_count: articles.length,
    news_skipped_reason: extras.news?.skipped_reason ?? null,
    evidence_links: brief?.evidence_links?.join(" | ") ?? "",
  };
}

function cellToString(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "boolean") return value ? "True" : "False";
  return String(value);
}

function escapeCsv(value: string): string {
  if (value === "") return "";
  if (/[",\n\r]/.test(value)) return `"${value.replace(/"/g, '""')}"`;
  return value;
}

export function buildCsv(leads: EnrichedLead[]): string {
  const rows = leads.map(flattenLead);
  const lines = [EXPORT_COLUMNS.join(",")];
  for (const row of rows) {
    lines.push(EXPORT_COLUMNS.map((c) => escapeCsv(cellToString(row[c]))).join(","));
  }
  return lines.join("\n") + "\n";
}

export function buildTsv(leads: EnrichedLead[]): string {
  const rows = leads.map(flattenLead);
  const lines = [EXPORT_COLUMNS.join("\t")];
  for (const row of rows) {
    lines.push(
      EXPORT_COLUMNS.map((c) => cellToString(row[c]).replace(/[\t\r\n]+/g, " ")).join("\t"),
    );
  }
  return lines.join("\n") + "\n";
}

export function downloadFile(content: string, filename: string, mime: string) {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
