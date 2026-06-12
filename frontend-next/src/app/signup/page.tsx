import { Suspense } from "react";

import { AuthPage } from "@/components/auth-page";

export default function Signup() {
  return (
    <Suspense fallback={null}>
      <AuthPage mode="signup" />
    </Suspense>
  );
}
