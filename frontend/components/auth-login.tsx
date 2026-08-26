"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { ArrowLeft, LockKeyhole, Mail, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { Badge, Button, Card } from "@/components/ui";
import { PageHeading } from "@/components/page-heading";

export function AuthLogin() {
  const router = useRouter();
  const auth = useAuth();
  const [signUpMode, setSignUpMode] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage(null);
    try {
      if (signUpMode) {
        const signedIn = await auth.signUp(email, password);
        setMessage(signedIn ? "Account created. Redirecting…" : "Account created. Check your email to confirm, then sign in.");
        if (signedIn) router.push("/");
      } else {
        await auth.signIn(email, password);
        router.push("/");
      }
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Authentication failed.");
    } finally {
      setSubmitting(false);
    }
  }

  if (auth.loading) return <Card className="skeleton h-80" aria-label="Loading authentication" />;
  if (!auth.configured) {
    return <>
      <PageHeading eyebrow="Workspace access" title="Supabase Auth is optional" description="The anonymous portfolio demo is available now. Add the public Supabase URL and anon key to enable workspace sign-in." />
      <Card className="max-w-2xl p-6">
        <Badge tone="warning">Not configured</Badge>
        <p className="mt-4 text-sm leading-6 text-[#697080]">Authenticated tenants also need the backend OIDC issuer, audience, JWKS URL, group mapping, and tenant source mapping before their data can be queried.</p>
        <Button asChild variant="secondary" className="mt-5"><Link href="/"><ArrowLeft size={15} /> Back to demo</Link></Button>
      </Card>
    </>;
  }
  if (auth.user) {
    return <Card className="max-w-2xl p-6"><Badge tone="success">Signed in</Badge><h2 className="mt-4 text-xl font-bold">{auth.user.email ?? "Workspace user"}</h2><p className="mt-2 text-sm text-[#697080]">Your verified token will be used for workspace and tenant-aware analytics.</p><Button className="mt-5" onClick={() => router.push("/")}>Open ProductLens</Button></Card>;
  }

  return <>
    <PageHeading eyebrow="Workspace access" title={signUpMode ? "Create a workspace account" : "Sign in to your workspace"} description="Use Supabase Auth for a verified workspace session. Anonymous demo access remains available from the main navigation." />
    <Card className="max-w-xl p-6">
      <form onSubmit={submit} className="space-y-4">
        <label className="block text-sm font-semibold" htmlFor="auth-email"><span className="mb-2 flex items-center gap-2"><Mail size={15} /> Email</span><input id="auth-email" type="email" required autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} className="h-11 w-full rounded-lg border border-[#dfe3ea] px-3 text-sm outline-none focus:border-[#635bff]" /></label>
        <label className="block text-sm font-semibold" htmlFor="auth-password"><span className="mb-2 flex items-center gap-2"><LockKeyhole size={15} /> Password</span><input id="auth-password" type="password" required minLength={6} autoComplete={signUpMode ? "new-password" : "current-password"} value={password} onChange={(event) => setPassword(event.target.value)} className="h-11 w-full rounded-lg border border-[#dfe3ea] px-3 text-sm outline-none focus:border-[#635bff]" /></label>
        {message && <p role="alert" className="rounded-lg bg-[#fff8ed] p-3 text-sm leading-5 text-[#855519]">{message}</p>}
        <Button type="submit" className="w-full" disabled={submitting}>{submitting ? "Working…" : signUpMode ? "Create account" : "Sign in"}</Button>
      </form>
      <div className="mt-5 flex items-start gap-2 rounded-lg bg-[#f8f9fb] p-3 text-xs leading-5 text-[#697080]"><ShieldCheck size={15} className="mt-0.5 shrink-0 text-[#16875d]" /><span>Tokens are sent to the backend in the Authorization header and validated server-side.</span></div>
      <button type="button" onClick={() => { setSignUpMode((value) => !value); setMessage(null); }} className="mt-5 text-sm font-semibold text-[#5148d9]">{signUpMode ? "Already have an account? Sign in" : "Need an account? Create one"}</button>
    </Card>
  </>;
}
