"use client";

import { useState } from "react";

import DetailDialog from "@/components/ui/DetailDialog";
import { ProviderForm } from "@/components/llm/ProviderForm";
import { useLlmConfigStatus } from "@/hooks/useLlmConfigStatus";

/**
 * First-run LLM provider modal (EPIC-023 PR4).
 *
 * Mounted app-wide. When the config status has loaded and reports the user has
 * no usable LLM configuration, it prompts them to create their first provider.
 * On a successful create it calls `refresh()` so the status flips to configured
 * and the modal closes.
 *
 * The modal is dismissible: the deployment default may already provide a
 * working configuration, so the user can opt out without configuring anything.
 */
export function FirstRunModal() {
  const { configured, refresh } = useLlmConfigStatus();
  const [dismissed, setDismissed] = useState(false);

  // Only surface once the status is known and explicitly unconfigured.
  const isOpen = configured === false && !dismissed;

  if (!isOpen) return null;

  return (
    <DetailDialog
      isOpen={isOpen}
      onClose={() => setDismissed(true)}
      title="Set up your AI provider"
    >
      <p className="mb-4 text-sm text-muted">
        Connect an LLM provider to enable AI extraction, summaries, and the
        advisor. OpenRouter offers free <code>:free</code> models to get started.
      </p>
      <ProviderForm
        submitLabel="Save provider"
        onCancel={() => setDismissed(true)}
        onCreated={() => {
          void refresh();
        }}
      />
    </DetailDialog>
  );
}
