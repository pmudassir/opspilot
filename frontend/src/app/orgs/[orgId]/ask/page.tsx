"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert, PageLoading } from "@/components/ui/feedback";
import {
  type AssistantAnswer,
  describeToolUse,
  exampleQuestions,
  QUESTION_MAX,
  QUESTION_MIN,
  segmentAnswer,
  useAsk,
} from "@/lib/assistant";
import { useMe } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { useCurrentOrg } from "@/lib/org";
import { useRequest } from "@/lib/requests";

export default function AskPage() {
  return (
    <Suspense fallback={<PageLoading />}>
      <AskView />
    </Suspense>
  );
}

function AskView() {
  const { organizationId, can } = useCurrentOrg();
  const enabled = useMe().data?.features.ai_assistant ?? false;
  const requestId = useSearchParams().get("request") ?? undefined;
  const [question, setQuestion] = useState("");
  const [asked, setAsked] = useState<string | null>(null);
  const ask = useAsk(organizationId);

  if (!enabled) {
    return (
      <p className="max-w-xl text-sm text-zinc-600">
        The assistant isn&apos;t switched on for this deployment. Everything else works as usual.
      </p>
    );
  }

  const trimmed = question.trim();
  const submit = (text: string) => {
    if (text.length < QUESTION_MIN || ask.isPending) return;
    setAsked(text);
    ask.mutate({ question: text, requestId });
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit(trimmed);
  };

  return (
    <section className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-lg font-semibold">Ask OpsPilot</h1>
        <p className="text-sm text-zinc-600">
          Answers come from requests you&apos;re allowed to see. It can look things up but can&apos;t change anything.
        </p>
      </div>

      {requestId && <RequestContext orgId={organizationId} requestId={requestId} />}

      <form onSubmit={onSubmit} className="flex flex-col gap-2">
        <label htmlFor="question" className="text-sm font-medium text-zinc-800">
          Your question
        </label>
        <textarea
          id="question"
          value={question}
          maxLength={QUESTION_MAX}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) onSubmit(event);
          }}
          placeholder={requestId ? "Who's working on this, and what happened so far?" : "Which urgent requests are still unassigned?"}
          className="min-h-20 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none placeholder:text-zinc-400 focus:border-teal-700 focus:ring-2 focus:ring-teal-700/20"
        />
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs text-zinc-500">
            {trimmed.length}/{QUESTION_MAX} · ⌘/Ctrl + Enter to ask
          </span>
          <Button type="submit" size="sm" pending={ask.isPending} disabled={trimmed.length < QUESTION_MIN}>
            {ask.isPending ? "Looking things up…" : "Ask"}
          </Button>
        </div>
      </form>

      {ask.isPending ? (
        <p role="status" className="text-sm text-zinc-500">
          Looking things up for “{asked}”. This usually takes a few seconds.
        </p>
      ) : ask.isError ? (
        <ErrorAlert error={ask.error} />
      ) : ask.data && asked ? (
        <Answer orgId={organizationId} question={asked} answer={ask.data} />
      ) : (
        <Examples
          questions={requestId ? ["Summarise this request", "Who could take this, and how busy are they?", "Can I cancel this?"] : exampleQuestions(can)}
          onPick={(text) => {
            setQuestion(text);
            submit(text);
          }}
        />
      )}
    </section>
  );
}

function RequestContext({ orgId, requestId }: { orgId: string; requestId: string }) {
  const request = useRequest(orgId, requestId);
  const router = useRouter();
  const pathname = usePathname();
  return (
    <div className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm">
      <span className="min-w-0 truncate text-zinc-700">
        About:{" "}
        <Link href={`/orgs/${orgId}/requests/${requestId}`} className="font-medium text-teal-800 hover:underline">
          {request.data?.title ?? "this request"}
        </Link>
      </span>
      <Button variant="ghost" size="sm" onClick={() => router.replace(pathname)}>
        Ask about everything
      </Button>
    </div>
  );
}

function Examples({ questions, onPick }: { questions: string[]; onPick: (question: string) => void }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-zinc-600">Try:</p>
      <ul className="flex flex-wrap gap-2">
        {questions.map((question) => (
          <li key={question}>
            <button
              type="button"
              onClick={() => onPick(question)}
              className="rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-left text-sm text-zinc-700 hover:border-teal-700 hover:text-teal-800"
            >
              {question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Answer({ orgId, question, answer }: { orgId: string; question: string; answer: AssistantAnswer }) {
  const lookups = [...new Set(answer.tools_used.map(describeToolUse))];
  return (
    <article aria-label="Answer" className="flex flex-col gap-3 rounded-md border border-zinc-200 bg-white p-4">
      <p className="text-sm text-zinc-500">{question}</p>
      <p className="text-sm leading-6 whitespace-pre-wrap text-zinc-900">
        {segmentAnswer(answer.answer, answer.references).map((segment, index) =>
          "text" in segment ? (
            <span key={index}>{segment.text}</span>
          ) : (
            <Link
              key={index}
              href={`/orgs/${orgId}/requests/${segment.reference.request_id}`}
              title={segment.reference.title}
              className="font-medium text-teal-800 underline decoration-teal-800/30 underline-offset-2 hover:decoration-teal-800"
            >
              {segment.reference.ref}
            </Link>
          ),
        )}
      </p>
      {answer.references.length > 0 && (
        <ul aria-label="Requests mentioned" className="flex flex-col gap-1 border-t border-zinc-100 pt-3 text-sm">
          {answer.references.map((reference) => (
            <li key={reference.ref}>
              <Link href={`/orgs/${orgId}/requests/${reference.request_id}`} className="text-teal-800 hover:underline">
                <span className="font-medium">{reference.ref}</span> · {reference.title}
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="border-t border-zinc-100 pt-3 text-xs text-zinc-500">
        {lookups.length > 0 ? `Looked up: ${lookups.join(", ")}.` : "Answered without looking anything up."} Read-only
        · AI can be wrong, so check the request before acting · {answer.model} · as of {formatDateTime(answer.as_of)}
      </p>
    </article>
  );
}
