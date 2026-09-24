import { OUTCOME_LABELS, OUTCOME_STYLES, USE_CASE_LABELS } from "@/lib/format";
import type { Outcome, UseCase } from "@/lib/types";

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${OUTCOME_STYLES[outcome]}`}
    >
      {OUTCOME_LABELS[outcome]}
    </span>
  );
}

export function UseCaseBadge({ useCase }: { useCase: UseCase }) {
  if (!useCase) {
    return <span className="text-xs text-zinc-400">—</span>;
  }
  return (
    <span className="inline-block rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
      {USE_CASE_LABELS[useCase]}
    </span>
  );
}
