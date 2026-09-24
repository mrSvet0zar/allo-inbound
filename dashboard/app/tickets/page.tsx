import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { api } from "@/lib/api";
import type { Ticket } from "@/lib/types";

export const revalidate = 0;

const PRIORITY_STYLES: Record<Ticket["priorite"], string> = {
  high: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  medium: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};

const PRIORITY_LABELS: Record<Ticket["priorite"], string> = {
  high: "Haute",
  medium: "Moyenne",
  low: "Basse",
};

export default async function TicketsPage() {
  let tickets;
  try {
    tickets = await api.tickets();
  } catch (error) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-xl font-semibold">Tickets ouverts</h1>
        <ApiErrorNotice error={error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Tickets ouverts</h1>

      {tickets.length === 0 ? (
        <p className="text-sm text-zinc-500">Aucun ticket ouvert.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {tickets.map((ticket) => (
            <li
              key={ticket.id}
              className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${PRIORITY_STYLES[ticket.priorite]}`}
                >
                  {PRIORITY_LABELS[ticket.priorite]}
                </span>
                {ticket.caller_phone && (
                  <span className="text-xs text-zinc-400">{ticket.caller_phone}</span>
                )}
              </div>
              <p className="mt-2 text-sm text-zinc-800 dark:text-zinc-200">{ticket.resume}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
