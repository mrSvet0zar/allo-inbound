import Link from "next/link";
import { notFound } from "next/navigation";

import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { OutcomeBadge, UseCaseBadge } from "@/components/Badge";
import { StatCard } from "@/components/StatCard";
import { ApiError, api } from "@/lib/api";
import { formatDateTime, formatDuration } from "@/lib/format";

export const revalidate = 0;

export default async function CallDetailPage({
  params,
}: {
  params: Promise<{ sid: string }>;
}) {
  const { sid } = await params;

  let call;
  try {
    call = await api.call(sid);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      notFound();
    }
    return <ApiErrorNotice error={error} />;
  }

  const lines = call.transcript.split("\n").filter(Boolean);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          ← Retour aux appels
        </Link>
        <h1 className="mt-2 flex items-center gap-3 text-xl font-semibold">
          Appel du {formatDateTime(call.created_at)}
          <OutcomeBadge outcome={call.outcome} />
        </h1>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Cas d'usage" value={call.use_case ?? "—"} />
        <StatCard label="Durée" value={formatDuration(call.duration_seconds)} />
        <StatCard
          label="Latence 1re syllabe"
          value={call.avg_turn_latency_ms !== null ? `${call.avg_turn_latency_ms}ms` : "—"}
        />
        <StatCard label="Appels d'outils" value={String(call.tool_calls_count)} />
      </div>

      {call.escalated_to_human && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
          Cet appel a été transféré à un conseiller humain.
        </div>
      )}

      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-zinc-500 dark:text-zinc-400">
          <span>Transcript</span>
          <UseCaseBadge useCase={call.use_case} />
        </div>
        <div className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          {lines.length === 0 ? (
            <p className="text-sm text-zinc-500">Transcript vide.</p>
          ) : (
            <ol className="flex flex-col gap-2 text-sm">
              {lines.map((line, i) => {
                const isAgent = line.startsWith("Agent :");
                return (
                  <li
                    key={i}
                    className={
                      isAgent
                        ? "text-zinc-900 dark:text-zinc-100"
                        : "text-zinc-500 dark:text-zinc-400"
                    }
                  >
                    {line}
                  </li>
                );
              })}
            </ol>
          )}
        </div>
      </div>
    </div>
  );
}
