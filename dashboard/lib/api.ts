import type {
  Appointment,
  CallDetail,
  CallSummary,
  KnowledgeBaseEntry,
  Stats,
  Ticket,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ADMIN_KEY = process.env.NEXT_PUBLIC_ADMIN_KEY;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: ADMIN_KEY ? { "X-Admin-Key": ADMIN_KEY } : undefined,
    // Le dashboard consulte des données quasi temps réel (appels en cours,
    // alertes) — pas de cache Next.js sur ces requêtes.
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiError(res.status, `${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  stats: () => get<Stats>("/admin/api/stats"),
  calls: (limit = 50) => get<CallSummary[]>(`/admin/api/calls?limit=${limit}`),
  call: (sid: string) => get<CallDetail>(`/admin/api/calls/${encodeURIComponent(sid)}`),
  appointments: (daysAhead = 7) =>
    get<Appointment[]>(`/admin/api/appointments?days_ahead=${daysAhead}`),
  tickets: () => get<Ticket[]>("/admin/api/tickets"),
  knowledgeBase: () => get<KnowledgeBaseEntry[]>("/admin/api/knowledge-base"),
};
