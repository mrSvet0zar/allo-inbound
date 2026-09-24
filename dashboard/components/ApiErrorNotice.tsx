export function ApiErrorNotice({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Erreur inconnue";
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
      <p className="font-medium">Impossible de joindre le serveur Allo-IA.</p>
      <p className="mt-1 text-red-700 dark:text-red-400">{message}</p>
      <p className="mt-2 text-xs text-red-600 dark:text-red-500">
        Vérifiez que le serveur temps réel tourne et que{" "}
        <code className="rounded bg-red-100 px-1 dark:bg-red-900">NEXT_PUBLIC_API_URL</code> pointe
        vers la bonne adresse.
      </p>
    </div>
  );
}
