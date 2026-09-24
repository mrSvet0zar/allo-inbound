import { AlertBanner } from "@/components/AlertBanner";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { CallsTable } from "@/components/CallsTable";
import { StatCard } from "@/components/StatCard";
import { api } from "@/lib/api";

export const revalidate = 0;

export default async function OverviewPage() {
  let stats, calls;
  try {
    [stats, calls] = await Promise.all([api.stats(), api.calls(20)]);
  } catch (error) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-xl font-semibold">Vue d&apos;ensemble</h1>
        <ApiErrorNotice error={error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Vue d&apos;ensemble</h1>

      <AlertBanner alerts={stats.alerts} />

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Appels récents" value={String(stats.calls_count)} hint="100 derniers" />
        <StatCard
          label="Latence moyenne"
          value={stats.avg_latency_ms !== null ? `${stats.avg_latency_ms}ms` : "—"}
          hint="Objectif < 1200ms"
        />
        <StatCard
          label="Taux d'escalade"
          value={
            stats.escalation_rate !== null ? `${Math.round(stats.escalation_rate * 100)}%` : "—"
          }
        />
        <StatCard label="Tickets ouverts" value={String(stats.open_tickets_count)} />
      </div>

      <div className="flex flex-col gap-3">
        <h2 className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
          Appels récents
        </h2>
        <CallsTable calls={calls} />
      </div>
    </div>
  );
}
