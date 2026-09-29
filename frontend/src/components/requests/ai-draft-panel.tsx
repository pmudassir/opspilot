"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert } from "@/components/ui/feedback";
import { DRAFT_TEXT_MAX, DRAFT_TEXT_MIN, type RequestDraft, useRequestDraft } from "@/lib/ai";

/** Free text → AI suggestion → pre-filled form. The person still reviews and submits. */
export function AiDraftPanel({ orgId, onDraft }: { orgId: string; onDraft: (draft: RequestDraft) => void }) {
  const [text, setText] = useState("");
  const draft = useRequestDraft(orgId);
  const tooShort = text.trim().length < DRAFT_TEXT_MIN;

  return (
    <section aria-labelledby="ai-draft" className="flex flex-col gap-2 rounded-md border border-teal-200 bg-teal-50/60 p-4">
      <h2 id="ai-draft" className="text-sm font-semibold text-teal-900">
        Describe it in your own words
      </h2>
      <p className="text-sm text-teal-900/80">AI will fill in the form below. You can change anything before submitting.</p>
      <label htmlFor="ai-draft-text" className="sr-only">
        Describe the problem
      </label>
      <textarea
        id="ai-draft-text"
        value={text}
        onChange={(event) => setText(event.target.value)}
        maxLength={DRAFT_TEXT_MAX}
        placeholder="The Wi-Fi in the second-floor meeting room keeps disconnecting and we have a client meeting in 20 minutes."
        className="min-h-20 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/20"
      />
      {draft.error && <ErrorAlert error={draft.error} />}
      <div>
        <Button
          size="sm"
          pending={draft.isPending}
          disabled={tooShort}
          onClick={() => draft.mutate(text.trim(), { onSuccess: onDraft })}
        >
          {draft.isPending ? "Drafting…" : "Draft with AI"}
        </Button>
      </div>
    </section>
  );
}

export function AiDraftNotice({ draft }: { draft: RequestDraft }) {
  return (
    <div role="status" className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
      <p>
        <span className="font-medium">Drafted by AI. Please review before submitting.</span> {draft.rationale}
      </p>
      {!draft.department_id && <p className="mt-1">It couldn&apos;t tell which department fits. Choose one below.</p>}
    </div>
  );
}
