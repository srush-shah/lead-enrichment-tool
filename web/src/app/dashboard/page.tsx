import Link from "next/link";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardHome() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Score a single lead, run a batch, or browse history.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <ShellCard
          title="New Lead"
          description="Paste a single property + contact, get tier, brief, and a draft email."
          href="/dashboard/new"
        />
        <ShellCard
          title="Bulk Upload"
          description="Drop a CSV. Watch results stream in. Export CSV or copy as TSV."
          href="/dashboard/bulk"
        />
        <ShellCard
          title="History"
          description="Past enrichments scoped to your account. Re-open or regenerate."
          href="/dashboard/history"
        />
      </div>
    </div>
  );
}

function ShellCard({
  title,
  description,
  href,
}: {
  title: string;
  description: string;
  href: string;
}) {
  return (
    <Link href={href} className="group">
      <Card className="h-full transition-colors group-hover:border-foreground/30">
        <CardHeader>
          <CardTitle className="text-base">{title}</CardTitle>
          <CardDescription>{description}</CardDescription>
        </CardHeader>
      </Card>
    </Link>
  );
}
