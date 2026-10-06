import { useMutation } from "@tanstack/react-query";

import { api, type Schemas, unwrap } from "@/lib/api/client";

export type AssistantAnswer = Schemas["AssistantAnswerOut"];
export type AnswerReference = Schemas["ReferenceOut"];
export type ToolUse = Schemas["ToolUseOut"];

export const QUESTION_MIN = 3;
export const QUESTION_MAX = 500;

export type AskInput = { question: string; requestId?: string };

/** Ask a question. Nothing is changed: at most a proposal is stored, which only the user can approve. */
export function useAsk(orgId: string) {
  return useMutation({
    mutationFn: ({ question, requestId }: AskInput) =>
      unwrap(
        api.POST("/api/v1/orgs/{org_id}/ai/assistant", {
          params: { path: { org_id: orgId } },
          body: { question, request_id: requestId ?? null },
        }),
      ),
  });
}

export type AnswerSegment = { text: string } | { reference: AnswerReference };

/**
 * Split an answer into text and request links. Only refs the server returned in
 * `references` become links: the model never supplies a URL or an id.
 */
export function segmentAnswer(answer: string, references: AnswerReference[]): AnswerSegment[] {
  const byRef = new Map(references.map((reference) => [reference.ref, reference]));
  const segments: AnswerSegment[] = [];
  let last = 0;
  for (const match of answer.matchAll(/\bR\d{1,3}\b/g)) {
    const reference = byRef.get(match[0]);
    if (!reference) continue;
    if (match.index > last) segments.push({ text: answer.slice(last, match.index) });
    segments.push({ reference });
    last = match.index + match[0].length;
  }
  if (last < answer.length) segments.push({ text: answer.slice(last) });
  return segments;
}

const TOOL_LABELS: Record<string, string> = {
  search_requests: "searched requests",
  get_request: "opened a request",
  get_request_history: "read a request's history",
  list_departments: "listed departments",
  get_department_status: "checked department metrics",
  list_department_staff: "checked department staff",
  propose_assign: "proposed an assignment",
  propose_unassign: "proposed unassigning",
  propose_cancel: "proposed cancelling",
  propose_priority: "proposed a priority change",
  propose_comment: "proposed a comment",
};

/** "searched requests", or "searched requests (not found)" when the lookup failed. */
export function describeToolUse(use: ToolUse): string {
  const label = TOOL_LABELS[use.tool] ?? "used an unknown tool";
  return use.status === "ok" || use.status === "repeated" ? label : `${label} (${use.status.replaceAll("_", " ")})`;
}

/** Example questions for the empty state, by what the role can see. */
export function exampleQuestions(can: (permission: Schemas["Permission"]) => boolean): string[] {
  if (!can("requests:read_all")) {
    return ["What's the status of my requests?", "Has anyone commented on my latest request?", "Which of my requests are still open?"];
  }
  return [
    "Which urgent or high-priority requests are unassigned?",
    "What's assigned to me right now?",
    ...(can("metrics:read") ? ["Which department has the biggest backlog this week?"] : []),
    ...(can("members:read") ? ["Who in IT has the fewest open assignments?"] : []),
  ];
}
