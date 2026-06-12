"use client";

import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { createUserWithEmailAndPassword, signInWithEmailAndPassword, updateProfile } from "firebase/auth";
import { Lock, Mail, Sparkles, User } from "lucide-react";
import { type FormEvent, useState } from "react";
import { getFirebaseAuth } from "@/lib/firebase";

type AuthMode = "login" | "signup";

type AuthPageProps = {
  mode: AuthMode;
};

const firebaseErrorMessages: Record<string, string> = {
  "auth/email-already-in-use": "That email already has a SPARX account. Try logging in instead.",
  "auth/invalid-credential": "Email or password is incorrect.",
  "auth/invalid-email": "Enter a valid email address.",
  "auth/operation-not-allowed": "Email/password auth is not enabled in Firebase.",
  "auth/too-many-requests": "Too many attempts. Wait a moment and try again.",
  "auth/weak-password": "Use at least 8 characters for your password.",
};

function authMessage(error: unknown) {
  if (typeof error === "object" && error && "code" in error) {
    const code = String(error.code);
    return firebaseErrorMessages[code] ?? "Firebase rejected this request. Please try again.";
  }
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

function SocialButton({
  children,
  icon,
}: {
  children: string;
  icon: React.ReactNode;
}) {
  return (
    <button
      aria-disabled="true"
      className="grid h-11 place-items-center rounded-[8px] bg-[#ffefd6] text-[var(--sparx-muted)] opacity-70"
      title={`${children} sign-in will be connected later`}
      type="button"
    >
      {icon}
    </button>
  );
}

function AuthInput({
  icon,
  label,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & {
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <label className="grid gap-1.5">
      <span className="sr-only">{label}</span>
      <span className="flex h-12 items-center gap-2 rounded-[8px] bg-[#ffefd6] px-3 text-[var(--sparx-muted)]">
        {icon}
        <input
          className="min-w-0 flex-1 bg-transparent text-sm font-semibold text-[var(--sparx-ink)] outline-none placeholder:text-[var(--sparx-muted)]"
          {...props}
        />
      </span>
    </label>
  );
}

export function AuthPage({ mode }: AuthPageProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const isSignup = mode === "signup";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");

    if (isSignup && name.trim().length < 2) {
      setMessage("Enter your name to create the account.");
      return;
    }
    if (password.length < 8) {
      setMessage("Password must be at least 8 characters.");
      return;
    }

    setBusy(true);
    try {
      const auth = getFirebaseAuth();
      if (isSignup) {
        const credential = await createUserWithEmailAndPassword(auth, email.trim().toLowerCase(), password);
        await updateProfile(credential.user, { displayName: name.trim() });
      } else {
        await signInWithEmailAndPassword(auth, email.trim().toLowerCase(), password);
      }
      router.push(searchParams.get("next") || "/");
    } catch (error) {
      setMessage(authMessage(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-[var(--sparx-page)] p-3 sm:p-6">
      <section className="mx-auto grid min-h-[calc(100vh-48px)] max-w-6xl gap-5 rounded-[28px] bg-white p-5 shadow-[0_22px_80px_rgba(40,32,20,0.08)] lg:grid-cols-[minmax(320px,420px)_minmax(0,1fr)] lg:p-9">
        <article className="grid content-center rounded-[24px] border border-[var(--sparx-line)] bg-[var(--sparx-panel)] px-6 py-10 text-center">
          <div className="mx-auto grid size-16 place-items-center rounded-[8px] bg-[var(--sparx-brand-soft)] text-white shadow-sm">
            <Sparkles className="size-10" strokeWidth={3} />
          </div>
          <p className="mt-3 text-xs font-black text-[var(--sparx-muted)]">Manage your calls</p>
          <h1 className="mt-8 text-[34px] font-black leading-none text-black">{isSignup ? "Sign Up" : "Log In"}</h1>
          <p className="mt-3 text-sm font-semibold text-[var(--sparx-muted)]">
            {isSignup ? "Enter your personal data to sign up" : "Use your SPARX account to continue"}
          </p>

          <form className="mx-auto mt-6 grid w-full max-w-[280px] gap-3 text-left" onSubmit={handleSubmit}>
            {isSignup ? (
              <AuthInput
                autoComplete="name"
                icon={<User className="size-4" />}
                label="Name"
                onChange={(event) => setName(event.target.value)}
                placeholder="Name"
                required
                value={name}
              />
            ) : null}
            <AuthInput
              autoComplete="email"
              icon={<Mail className="size-4" />}
              label="Email"
              onChange={(event) => setEmail(event.target.value)}
              placeholder="Email"
              required
              type="email"
              value={email}
            />
            <AuthInput
              autoComplete={isSignup ? "new-password" : "current-password"}
              icon={<Lock className="size-4" />}
              label="Password"
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password"
              required
              type="password"
              value={password}
            />

            <div className="my-2 flex items-center gap-3 text-center text-xs font-semibold text-[var(--sparx-muted)]">
              <span className="h-px flex-1 bg-[var(--sparx-line)]" />
              or
              <span className="h-px flex-1 bg-[var(--sparx-line)]" />
            </div>

            <div className="grid grid-cols-3 gap-3">
              <SocialButton icon={<span className="text-sm font-black">G</span>}>Google</SocialButton>
              <SocialButton icon={<span className="text-sm font-black">@</span>}>GitHub</SocialButton>
              <SocialButton icon={<span className="text-xs font-black">in</span>}>LinkedIn</SocialButton>
            </div>

            {message ? (
              <p className="rounded-[8px] border border-[var(--sparx-red)] bg-[rgba(255,88,78,0.08)] px-3 py-2 text-center text-xs font-black text-[var(--sparx-red)]">
                {message}
              </p>
            ) : null}

            <button
              className="mt-1 min-h-11 rounded-full bg-[var(--sparx-card-strong)] px-5 text-sm font-black text-white transition hover:bg-[var(--sparx-olive)] disabled:cursor-not-allowed disabled:opacity-60"
              disabled={busy}
              type="submit"
            >
              {busy ? "Checking..." : isSignup ? "Sign Up" : "Log In"}
            </button>
          </form>

          <p className="mt-5 text-xs font-semibold text-[var(--sparx-muted)]">
            {isSignup ? "Already have an Account? " : "Need an account? "}
            <Link className="font-black text-black underline" href={isSignup ? "/login" : "/signup"}>
              {isSignup ? "Log in" : "Sign up"}
            </Link>
          </p>
        </article>

        <aside className="hidden min-h-[420px] overflow-hidden rounded-[20px] bg-[#edf1f8] lg:block">
          <Image
            alt="SPARX calling interface"
            className="h-full w-full object-cover"
            height={1254}
            src="/sparx-assets/phone-mosaic.svg"
            width={1254}
          />
        </aside>
      </section>
    </main>
  );
}
