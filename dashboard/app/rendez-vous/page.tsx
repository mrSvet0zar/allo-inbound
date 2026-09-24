import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export const revalidate = 0;

export default async function AppointmentsPage() {
  let appointments;
  try {
    appointments = await api.appointments(7);
  } catch (error) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="text-xl font-semibold">Rendez-vous à venir</h1>
        <ApiErrorNotice error={error} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Rendez-vous à venir</h1>
      <p className="text-sm text-zinc-500">Sept prochains jours, RDV confirmés uniquement.</p>

      {appointments.length === 0 ? (
        <p className="text-sm text-zinc-500">Aucun rendez-vous à venir.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500 dark:bg-zinc-900 dark:text-zinc-400">
              <tr>
                <th className="px-4 py-2 font-medium">Date et heure</th>
                <th className="px-4 py-2 font-medium">Nom</th>
                <th className="px-4 py-2 font-medium">Motif</th>
                <th className="px-4 py-2 font-medium">Téléphone</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {appointments.map((appt) => (
                <tr key={appt.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-900">
                  <td className="px-4 py-2.5 text-zinc-900 dark:text-zinc-100">
                    {formatDateTime(appt.scheduled_at)}
                  </td>
                  <td className="px-4 py-2.5">{appt.nom}</td>
                  <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">{appt.motif}</td>
                  <td className="px-4 py-2.5 text-zinc-600 dark:text-zinc-400">
                    {appt.caller_phone ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
