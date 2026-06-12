import { Suspense } from "react";

import { AuthPage } from "@/components/auth-page";

export default function Login() {
  return (
    <Suspense fallback={null}>
      <AuthPage mode="login" />
    </Suspense>
  );
}
