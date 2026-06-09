import {
  AppShell,
  EmptyState,
  FormField,
  GreetingHeader,
  PageCanvas,
  PrimaryButton,
  ScrollPanel,
  StatCard,
  StatusBadge,
  UploadPanel,
  previewIcons,
} from "@/components/design-system";

export default function Home() {
  return (
    <AppShell>
      <GreetingHeader />
      <PageCanvas
        eyebrow="Shared foundation"
        title="Design System"
        actions={
          <>
            <StatusBadge tone="active">System Active</StatusBadge>
            <PrimaryButton icon={previewIcons.settings}>Preview</PrimaryButton>
          </>
        }
      >
        <div className="grid gap-5">
          <section className="grid gap-4 lg:grid-cols-4">
            <StatCard
              label="Active Calls"
              value="00"
              caption="Real-time Sessions"
              icon={previewIcons.calls}
            />
            <StatCard
              label="Transcripts"
              value="00"
              caption="Live utterances"
              icon={previewIcons.transcript}
            />
            <StatCard
              label="Meetings"
              value="08"
              caption="Booked Outcomes"
              icon={previewIcons.success}
              tone="olive"
            />
            <StatCard
              label="Warnings"
              value="03"
              caption="Needs Review"
              icon={previewIcons.warning}
              tone="white"
            />
          </section>

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_330px]">
            <div className="sparx-grid rounded-[8px] bg-white/72 p-4">
              <div className="mb-4 flex flex-wrap gap-2">
                <StatusBadge tone="active">Available</StatusBadge>
                <StatusBadge tone="warning">Processing</StatusBadge>
                <StatusBadge tone="danger">Failed</StatusBadge>
                <StatusBadge>Neutral</StatusBadge>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <FormField label="Campaign" placeholder="May Renewal List" />
                <FormField label="Agent Name" placeholder="Shasha" />
                <FormField label="Company" placeholder="Techsmith" />
                <FormField label="Persona" placeholder="Renewal Specialist" />
                <FormField
                  label="Primary List"
                  placeholder="May Renewal List"
                  wide
                />
              </div>
            </div>
            <div className="grid gap-4">
              <UploadPanel />
              <EmptyState
                title="Queue is Empty"
                description="Add content to your queue to get started."
              />
            </div>
          </section>

          <ScrollPanel>
            <div className="grid gap-3">
              {["Bhavesh Pandey", "Manish Sharma", "Rakesh Sharma"].map(
                (name, index) => (
                  <article
                    className="flex flex-col gap-3 rounded-[8px] bg-white p-4 shadow-sm sm:flex-row sm:items-center sm:justify-between"
                    key={name}
                  >
                    <div className="min-w-0">
                      <StatusBadge tone={index === 0 ? "active" : "neutral"}>
                        {index === 0 ? "Online" : "Scheduled"}
                      </StatusBadge>
                      <h3 className="mt-2 truncate text-xl font-black">
                        {name}
                      </h3>
                      <p className="text-sm font-semibold text-[var(--sparx-muted)]">
                        Follow-up for outstanding payment.
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-2">
                      <PrimaryButton icon={previewIcons.calls}>Dial</PrimaryButton>
                      <PrimaryButton variant="soft" icon={previewIcons.success}>
                        Done
                      </PrimaryButton>
                    </div>
                  </article>
                ),
              )}
            </div>
          </ScrollPanel>
        </div>
      </PageCanvas>
    </AppShell>
  );
}
