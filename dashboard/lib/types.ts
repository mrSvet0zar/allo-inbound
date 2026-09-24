export type UseCase = "rdv" | "support" | null;

export type Outcome =
  | "booked"
  | "cancelled"
  | "resolved"
  | "escalated"
  | "abandoned";

export interface CallSummary {
  twilio_call_sid: string;
  use_case: UseCase;
  duration_seconds: number;
  outcome: Outcome;
  escalated_to_human: boolean;
  avg_turn_latency_ms: number | null;
  tool_calls_count: number;
  created_at: number; // epoch seconds
}

export interface CallDetail extends CallSummary {
  transcript: string;
}

export interface Appointment {
  id: number;
  scheduled_at: string; // ISO
  nom: string;
  motif: string;
  caller_phone: string | null;
  status: string;
}

export interface Ticket {
  id: number;
  resume: string;
  priorite: "low" | "medium" | "high";
  caller_phone: string | null;
  status: string;
}

export interface KnowledgeBaseEntry {
  id: number;
  question: string;
  answer: string;
}

export interface Alert {
  level: "warning" | "critical";
  message: string;
}

export interface Stats {
  calls_count: number;
  avg_latency_ms: number | null;
  escalation_rate: number | null;
  open_tickets_count: number;
  alerts: Alert[];
}
