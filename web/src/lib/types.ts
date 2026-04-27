export type Tier = "A" | "B" | "C" | "D" | "Skipped";

export type LeadInput = {
  name: string;
  email: string;
  company: string;
  property_address: string;
  city: string;
  state: string;
  country: string;
};

export type SubScores = {
  mps: number;
  market_fit: number;
  company_fit: number;
  timing: number;
  geographic: number;
  pre_score: number;
};

export type LeadBrief = {
  why_now: string;
  why_now_source: "news" | "market" | "company" | "none";
  talking_point: string;
  objection_preempt: string | null;
  evidence_links: string[];
};

export type NewsArticle = {
  title: string;
  url: string;
  published_at: string;
  source: string;
  description: string | null;
};

export type EnrichedLead = {
  input: LeadInput;
  msa: string | null;
  in_top25_msa: boolean;
  corporate_domain: boolean;
  sub_scores: SubScores | null;
  score: number | null;
  tier: Tier;
  skipped_reason: string | null;
  brief: LeadBrief | null;
  draft_email_subject: string | null;
  draft_email_body: string | null;
  enriched_at: string;
  news?: { articles: NewsArticle[] };
  company?: { wiki_url?: string | null; has_wikipedia?: boolean };
};
