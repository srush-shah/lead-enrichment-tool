"use client";

import { useState } from "react";
import { CopyIcon, PencilIcon, RefreshCwIcon, CheckIcon, XIcon, ExternalLinkIcon } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EnrichedLead, SubScores, Tier } from "@/lib/types";

const SUB_SCORE_LABELS: Array<{ key: keyof SubScores; label: string }> = [
  { key: "mps", label: "Multifamily prob" },
  { key: "market_fit", label: "Market fit" },
  { key: "company_fit", label: "Company fit" },
  { key: "timing", label: "Timing" },
  { key: "geographic", label: "Geographic" },
];

const TIER_VARIANT: Record<Tier, "default" | "secondary" | "outline" | "destructive"> = {
  A: "default",
  B: "secondary",
  C: "outline",
  D: "outline",
  Skipped: "destructive",
};

export function LeadResultCard({
  lead,
  onUpdate,
}: {
  lead: EnrichedLead & { id?: number };
  onUpdate?: (lead: EnrichedLead & { id?: number }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [subject, setSubject] = useState(lead.draft_email_subject ?? "");
  const [body, setBody] = useState(lead.draft_email_body ?? "");
  const [regenerating, setRegenerating] = useState(false);

  async function copyEmail() {
    const text = `Subject: ${subject}\n\n${body}`;
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Email copied to clipboard");
    } catch {
      toast.error("Copy failed — select and copy manually");
    }
  }

  async function regenerate() {
    if (!lead.id) {
      toast.error("Save the lead before regenerating");
      return;
    }
    setRegenerating(true);
    try {
      const res = await fetch(`/api/proxy/leads/${lead.id}/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const msg =
          res.status === 404
            ? "Regenerate ships in Step 5 — backend route not live yet."
            : `Regenerate failed (${res.status})`;
        toast.error(msg);
        return;
      }
      const next = (await res.json()) as EnrichedLead;
      onUpdate?.({ ...next, id: lead.id });
      toast.success("Email redrafted");
    } catch {
      toast.error("Network error during regenerate");
    } finally {
      setRegenerating(false);
    }
  }

  const tierVariant = TIER_VARIANT[lead.tier];
  const score = lead.score != null ? Math.round(lead.score) : null;

  return (
    <Card>
      <CardHeader className="border-b pb-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle className="text-lg">
            {lead.input.name}
            <span className="text-muted-foreground font-normal"> — {lead.input.company}</span>
          </CardTitle>
          <Badge variant={tierVariant} className="font-mono">
            Tier {lead.tier}
          </Badge>
          {score != null && (
            <Badge variant="outline" className="font-mono">
              Score {score}
            </Badge>
          )}
          {lead.msa && (
            <Badge variant="ghost" className="font-mono">
              {lead.msa}
              {lead.in_top25_msa ? " · top-25" : ""}
            </Badge>
          )}
        </div>
        <p className="text-xs text-muted-foreground">
          {lead.input.property_address}, {lead.input.city}, {lead.input.state}
        </p>
      </CardHeader>

      <CardContent className="space-y-5">
        {lead.skipped_reason && (
          <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <span className="font-medium">Skipped:</span> {lead.skipped_reason}
          </div>
        )}

        {lead.sub_scores && <SubScoreBars scores={lead.sub_scores} />}

        {lead.brief && (
          <div className="space-y-3">
            <BriefBlock label="Why now" body={lead.brief.why_now} source={lead.brief.why_now_source} />
            <BriefBlock label="Talking point" body={lead.brief.talking_point} />
            {lead.brief.objection_preempt && (
              <BriefBlock label="Objection preempt" body={lead.brief.objection_preempt} />
            )}
            {lead.brief.evidence_links.length > 0 && (
              <div className="text-xs">
                <span className="font-medium text-muted-foreground">Evidence: </span>
                {lead.brief.evidence_links.map((url, i) => (
                  <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary hover:underline"
                  >
                    [{i + 1}]
                    {i < lead.brief!.evidence_links.length - 1 ? " " : ""}
                  </a>
                ))}
              </div>
            )}
          </div>
        )}

        {(lead.draft_email_subject || lead.draft_email_body) && (
          <div className="rounded-lg border bg-muted/30 p-3">
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Draft email
              </span>
              <div className="flex items-center gap-1">
                {!editing ? (
                  <>
                    <Button size="xs" variant="ghost" onClick={copyEmail}>
                      <CopyIcon /> Copy
                    </Button>
                    <Button size="xs" variant="ghost" onClick={() => setEditing(true)}>
                      <PencilIcon /> Edit
                    </Button>
                    {lead.id != null && (
                      <Button
                        size="xs"
                        variant="ghost"
                        onClick={regenerate}
                        disabled={regenerating}
                      >
                        <RefreshCwIcon className={regenerating ? "animate-spin" : ""} /> Regenerate
                      </Button>
                    )}
                  </>
                ) : (
                  <>
                    <Button size="xs" variant="ghost" onClick={() => setEditing(false)}>
                      <CheckIcon /> Done
                    </Button>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => {
                        setSubject(lead.draft_email_subject ?? "");
                        setBody(lead.draft_email_body ?? "");
                        setEditing(false);
                      }}
                    >
                      <XIcon /> Cancel
                    </Button>
                  </>
                )}
              </div>
            </div>
            {editing ? (
              <div className="space-y-2">
                <input
                  className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  placeholder="Subject"
                />
                <textarea
                  className="min-h-[180px] w-full rounded-md border border-input bg-background p-2.5 text-sm leading-relaxed outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                />
              </div>
            ) : (
              <div className="space-y-2 text-sm">
                <div>
                  <span className="text-xs text-muted-foreground">Subject</span>
                  <p className="font-medium">{subject || <em className="text-muted-foreground">No subject</em>}</p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Body</span>
                  <pre className="whitespace-pre-wrap font-sans leading-relaxed">
                    {body || <em className="text-muted-foreground">No body</em>}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}

        {lead.news?.articles && lead.news.articles.length > 0 && (
          <div>
            <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
              Recent news
            </span>
            <ul className="mt-2 space-y-1 text-xs">
              {lead.news.articles.slice(0, 3).map((a) => (
                <li key={a.url} className="truncate">
                  <a
                    href={a.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-primary hover:underline"
                  >
                    {a.title} <ExternalLinkIcon className="inline size-3" />
                  </a>
                  <span className="text-muted-foreground"> — {a.source}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SubScoreBars({ scores }: { scores: SubScores }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {SUB_SCORE_LABELS.map(({ key, label }) => {
        const value = scores[key] ?? 0;
        const pct = Math.max(0, Math.min(100, value));
        return (
          <div key={key} className="space-y-1">
            <div className="flex justify-between text-xs">
              <span className="text-muted-foreground">{label}</span>
              <span className="font-mono tabular-nums">{Math.round(value)}</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary transition-all"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function BriefBlock({
  label,
  body,
  source,
}: {
  label: string;
  body: string;
  source?: string;
}) {
  return (
    <div>
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          {label}
        </span>
        {source && source !== "none" && (
          <Badge variant="ghost" className="font-mono text-[10px]">
            {source}
          </Badge>
        )}
      </div>
      <p className="text-sm leading-relaxed">{body}</p>
    </div>
  );
}
