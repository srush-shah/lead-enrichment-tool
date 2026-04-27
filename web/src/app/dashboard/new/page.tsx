"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowLeftIcon, SparklesIcon } from "lucide-react";
import { toast } from "sonner";
import { LeadResultCard } from "@/components/lead-result-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { EnrichedLead, LeadInput } from "@/lib/types";

const EMPTY: LeadInput = {
  name: "",
  email: "",
  company: "",
  property_address: "",
  city: "",
  state: "",
  country: "USA",
};

const SAMPLE: LeadInput = {
  name: "Sarah Chen",
  email: "schen@greystar.com",
  company: "Greystar",
  property_address: "465 West 23rd Street",
  city: "New York",
  state: "NY",
  country: "USA",
};

export default function NewLeadPage() {
  const [form, setForm] = useState<LeadInput>(EMPTY);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<EnrichedLead | null>(null);

  function update<K extends keyof LeadInput>(key: K, value: LeadInput[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function loadSample() {
    setForm(SAMPLE);
  }

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    setResult(null);
    try {
      const res = await fetch("/api/proxy/enrich", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (res.status === 401) {
        toast.error("Session expired — please sign in again");
        window.location.href = "/login";
        return;
      }
      if (!res.ok) {
        const text = await res.text();
        toast.error(`Enrichment failed (${res.status}) — ${text.slice(0, 120)}`);
        return;
      }
      const enriched = (await res.json()) as EnrichedLead;
      setResult(enriched);
      toast.success(`Enriched — Tier ${enriched.tier}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Network error");
    } finally {
      setSubmitting(false);
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
        <h1 className="text-xl font-semibold tracking-tight">New lead</h1>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(320px,400px)_1fr]">
        <Card>
          <CardHeader className="border-b pb-3">
            <CardTitle className="text-base">Lead details</CardTitle>
            <CardDescription>
              Property + contact. Backend runs scoring, news, and email draft.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-3">
              <Field label="Name" required>
                <Input
                  required
                  value={form.name}
                  onChange={(e) => update("name", e.target.value)}
                  placeholder="Sarah Chen"
                />
              </Field>
              <Field label="Work email" required>
                <Input
                  type="email"
                  required
                  value={form.email}
                  onChange={(e) => update("email", e.target.value)}
                  placeholder="schen@greystar.com"
                />
              </Field>
              <Field label="Company" required>
                <Input
                  required
                  value={form.company}
                  onChange={(e) => update("company", e.target.value)}
                  placeholder="Greystar"
                />
              </Field>
              <Field label="Property address" required>
                <Input
                  required
                  value={form.property_address}
                  onChange={(e) => update("property_address", e.target.value)}
                  placeholder="465 West 23rd Street"
                />
              </Field>
              <div className="grid grid-cols-[1fr_80px] gap-2">
                <Field label="City" required>
                  <Input
                    required
                    value={form.city}
                    onChange={(e) => update("city", e.target.value)}
                    placeholder="New York"
                  />
                </Field>
                <Field label="State" required>
                  <Input
                    required
                    maxLength={2}
                    value={form.state}
                    onChange={(e) => update("state", e.target.value.toUpperCase())}
                    placeholder="NY"
                  />
                </Field>
              </div>
              <Field label="Country">
                <Input
                  value={form.country}
                  onChange={(e) => update("country", e.target.value)}
                />
              </Field>

              <div className="flex items-center justify-between gap-2 pt-2">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={loadSample}
                  disabled={submitting}
                >
                  Use sample
                </Button>
                <Button type="submit" disabled={submitting}>
                  <SparklesIcon className={submitting ? "animate-pulse" : ""} />
                  {submitting ? "Enriching…" : "Enrich"}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>

        <div>
          {result ? (
            <LeadResultCard
              key={result.enriched_at}
              lead={result}
              onUpdate={(next) => setResult(next)}
            />
          ) : (
            <EmptyState submitting={submitting} />
          )}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">
        {label}
        {required && <span className="text-destructive">*</span>}
      </Label>
      {children}
    </div>
  );
}

function EmptyState({ submitting }: { submitting: boolean }) {
  return (
    <Card className="h-full">
      <CardContent className="text-muted-foreground flex h-full min-h-[320px] flex-col items-center justify-center gap-2 text-center text-sm">
        <SparklesIcon className={`size-6 ${submitting ? "animate-pulse" : "opacity-40"}`} />
        {submitting ? (
          <p>
            Running geo, market, news, and Gemini draft.
            <br />
            First call after a cold start can take ~30 sec.
          </p>
        ) : (
          <p>
            Submit the form to score the lead and draft an email.
            <br />
            Try “Use sample” for a known A-tier example.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
