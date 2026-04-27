import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";

export default function AccessDeniedPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-xl">Access denied</CardTitle>
          <CardDescription>
            That Google account isn&apos;t on the assessment allowlist. Contact
            srushti1010shah@gmail.com if you should have access.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Link
            href="/login"
            className={buttonVariants({ variant: "outline", className: "w-full" })}
          >
            Back to sign in
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}
