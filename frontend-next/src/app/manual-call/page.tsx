import { Suspense } from "react";
import { ManualCallPage } from "@/components/pages";
import { loadInitialPlatformData } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export default async function Page() {
  const initialData = await loadInitialPlatformData();

  return (
    <Suspense>
      <ManualCallPage initialData={initialData} />
    </Suspense>
  );
}
