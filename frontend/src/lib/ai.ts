import { useMutation } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export type RequestDraft = Schemas["RequestDraftOut"];

export const DRAFT_TEXT_MIN = 10;
export const DRAFT_TEXT_MAX = 2000;

/** Ask the API for a draft. Nothing is saved: the result only pre-fills the form. */
export function useRequestDraft(orgId: string) {
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(
        api.POST("/api/v1/orgs/{org_id}/ai/request-drafts", {
          params: { path: { org_id: orgId } },
          body: { text },
        }),
      ),
  });
}
