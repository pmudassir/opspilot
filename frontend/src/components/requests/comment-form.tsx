"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { ErrorAlert } from "@/components/ui/feedback";
import { useAddComment } from "@/lib/requests";

const COMMENT_MAX_LENGTH = 5000;

export function CommentForm({ orgId, requestId }: { orgId: string; requestId: string }) {
  const [body, setBody] = useState("");
  const addComment = useAddComment(orgId, requestId);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!body.trim()) return;
    addComment.mutate(body, { onSuccess: () => setBody("") });
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      {addComment.error && <ErrorAlert error={addComment.error} />}
      <label htmlFor="comment" className="sr-only">
        Add a comment
      </label>
      <textarea
        id="comment"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        maxLength={COMMENT_MAX_LENGTH}
        placeholder="Add a comment or an update…"
        className="min-h-20 rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/20"
      />
      <div>
        <Button type="submit" size="sm" pending={addComment.isPending} disabled={!body.trim()}>
          Comment
        </Button>
      </div>
    </form>
  );
}
