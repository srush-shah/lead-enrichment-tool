import { redirect } from "next/navigation";
import { auth, signIn } from "@/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

type SearchParams = Promise<{ callbackUrl?: string; error?: string }>;

export default async function LoginPage({ searchParams }: { searchParams: SearchParams }) {
  const session = await auth();
  if (session?.user?.email) redirect("/dashboard");

  const params = await searchParams;
  const callbackUrl = params.callbackUrl ?? "/dashboard";
  const error = params.error;

  return (
    <main className="flex flex-1 items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-xl">Sign in</CardTitle>
          <CardDescription>
            Elise GTM lead enrichment — access is limited to allowlisted Google
            accounts during the assessment.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              Sign-in failed: {error}
            </p>
          ) : null}
          <form
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: callbackUrl });
            }}
          >
            <Button type="submit" className="w-full">
              Continue with Google
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
