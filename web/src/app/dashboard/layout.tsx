import { redirect } from "next/navigation";
import { auth, signOut } from "@/auth";
import { QuotaChips } from "@/components/quota-chips";
import { QuotaWarning } from "@/components/quota-warning";
import { Button } from "@/components/ui/button";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await auth();
  if (!session?.user?.email) redirect("/login");

  return (
    <div className="flex flex-1 flex-col">
      <header className="border-b border-border/60 bg-background">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-3">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold">Elise GTM</span>
            <span className="text-xs text-muted-foreground hidden sm:inline">
              Lead enrichment
            </span>
          </div>
          <div className="flex items-center gap-3">
            <QuotaChips />
            <span className="hidden text-xs text-muted-foreground md:inline">
              {session.user.email}
            </span>
            <form
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/login" });
              }}
            >
              <Button type="submit" variant="ghost" size="sm">
                Sign out
              </Button>
            </form>
          </div>
        </div>
      </header>
      <div className="mx-auto w-full max-w-6xl flex-1 px-6 py-6">
        <QuotaWarning />
        {children}
      </div>
    </div>
  );
}
