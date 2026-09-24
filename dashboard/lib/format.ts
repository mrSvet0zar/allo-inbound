import type { Outcome, UseCase } from "./types";

export function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m} min ${s}s` : `${s}s`;
}

export function formatDateTime(value: string | number): string {
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return date.toLocaleString("fr-FR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Europe/Paris",
  });
}

export const OUTCOME_LABELS: Record<Outcome, string> = {
  booked: "Réservé",
  cancelled: "Annulé",
  resolved: "Résolu",
  escalated: "Escaladé",
  abandoned: "Abandonné",
};

export const OUTCOME_STYLES: Record<Outcome, string> = {
  booked: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  resolved: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  cancelled: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  escalated: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  abandoned: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
};

export const USE_CASE_LABELS: Record<NonNullable<UseCase>, string> = {
  rdv: "Rendez-vous",
  support: "Support",
};
