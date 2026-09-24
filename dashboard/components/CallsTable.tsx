import Link from "next/link";

import { OutcomeBadge, UseCaseBadge } from "@/components/Badge";
import { formatDateTime, formatDuration } from "@/lib/format";
import type { CallSummary } from "@/lib/types";

export function CallsTable({ calls }: { calls: CallSummary[] }) {
  if (calls.length === 0) {
    return <p className="text-sm text-zinc-500">Aucun appel pour le moment.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-sm">
        <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            <th className="px-4 py-2 font-medium">Date</th>
            <th className="px-4 py-2 font-medium">Cas d&apos;usage</th>
            <th className="px-4 py-2 font-medium">Résultat</th>
            <th className="px-4 py-2 font-medium">Durée</th>
            <th className="px-4 py-2 font-medium">Latence 1re syllabe</th>
            <th className="px-4 py-2 font-medium">Outils</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {calls.map((call) => (
            <tr key={call.twilio_call_sid} className="hover:bg-zinc-50 dark:hover:bg-zinc-900">
              <td className="px-4 py-2.5">
                <Link
                  href={`/appels/${encodeURIComponent(call.twilio_call_sid)}`}
                  className="text-zinc-900 underline-offset-2 hover:underline dark:text-zinc-100"
                >
                  {formatDateTime(call.created_at)}
                </Link>
              </td>
              <td className="px-4 py-2.5">
                <UseCaseBadge useCase={call.use_case} />
              </td>
              <td className="px-4 py-2.5">
                <OutcomeBadge outcome={call.outcome} />
              </td>
              <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">
                {formatDuration(call.duration_seconds)}
              </td>
              <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">
                {call.avg_turn_latency_ms !== null ? `${call.avg_turn_latency_ms}ms` : "—"}
              </td>
              <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">
                {call.tool_calls_count}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
