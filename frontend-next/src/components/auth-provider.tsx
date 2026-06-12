"use client";

import { onAuthStateChanged, signOut, type User as FirebaseUser } from "firebase/auth";
import { usePathname, useRouter } from "next/navigation";
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";
import { getFirebaseAuth } from "@/lib/firebase";

type AuthContextValue = {
  user: FirebaseUser | null;
  loading: boolean;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);
const publicPaths = new Set(["/login", "/signup"]);

export function AuthProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<FirebaseUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const auth = getFirebaseAuth();
    return onAuthStateChanged(auth, (nextUser) => {
      setUser(nextUser);
      setLoading(false);

      const isPublicPath = publicPaths.has(pathname);
      if (!nextUser && !isPublicPath) {
        router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      }
      if (nextUser && isPublicPath) {
        router.replace("/");
      }
    });
  }, [pathname, router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      async logout() {
        await signOut(getFirebaseAuth());
        router.replace("/login");
      },
    }),
    [loading, router, user],
  );

  const isPublicPath = publicPaths.has(pathname);
  if (loading && !isPublicPath) {
    return (
      <main className="grid min-h-screen place-items-center bg-[var(--sparx-canvas)]">
        <div className="rounded-[8px] bg-[var(--sparx-panel)] px-5 py-4 text-sm font-black text-[var(--sparx-muted)]">
          Checking session...
        </div>
      </main>
    );
  }

  if (!loading && !user && !isPublicPath) {
    return null;
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider.");
  }
  return context;
}
