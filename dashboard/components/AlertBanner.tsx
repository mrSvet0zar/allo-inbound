import type { Alert } from "@/lib/types";

export function AlertBanner({ alerts }: { alerts: Alert[] }) {
  if (alerts.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {alerts.map((alert, i) => (
        <div
          key={i}
          className={
            "rounded-lg border px-4 py-3 text-sm " +
            (alert.level === "critical"
              ? "border-red-300 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
              : "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300")
          }
        >
          <span className="font-medium">
            {alert.level === "critical" ? "Critique — " : "Attention — "}
          </span>
          {alert.message}
        </div>
      ))}
    </div>
  );
}
