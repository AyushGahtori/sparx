import { Suspense } from "react";
import { TranscriptPage } from "@/components/pages";
import { loadInitialPlatformData } from "@/lib/server-data";

export const dynamic = "force-dynamic";

export default async function Page() {
  const initialData = await loadInitialPlatformData();
  return (
    <Suspense>
      <TranscriptPage initialData={initialData} />
    </Suspense>
  );
}
