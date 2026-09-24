export const metadata = {
  title: "Transparence & consentement — Allo-IA",
};

export default function TransparencyPage() {
  return (
    <div className="flex max-w-2xl flex-col gap-1">
      <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">
        Transparence et consentement
      </h1>
      <p className="text-zinc-600 dark:text-zinc-400">
        Cette page décrit, en toute transparence, comment fonctionne l&apos;assistant vocal
        Allo-IA et quels sont vos droits en tant qu&apos;appelant.
      </p>

      <h2 className="mt-6 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Vous parlez à une intelligence artificielle
      </h2>
      <p className="text-zinc-600 dark:text-zinc-400">
        Dès le début de l&apos;appel, l&apos;assistant vocal s&apos;annonce clairement comme
        un système automatisé — il ne se fait jamais passer pour une personne. C&apos;est
        une obligation légale en France pour l&apos;usage de voix synthétiques dans un
        contexte commercial.
      </p>

      <h2 className="mt-6 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Enregistrement et transcription
      </h2>
      <p className="text-zinc-600 dark:text-zinc-400">
        L&apos;appel est transcrit afin d&apos;assurer le service (comprendre votre demande,
        vérifier les disponibilités, créer un ticket si nécessaire) et d&apos;améliorer la
        qualité de l&apos;assistant. Cette transcription vous est annoncée oralement en
        début d&apos;appel, conformément aux obligations RGPD et aux recommandations de la
        CNIL sur l&apos;enregistrement téléphonique.
      </p>

      <h2 className="mt-6 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Parler à un humain, à tout moment
      </h2>
      <p className="text-zinc-600 dark:text-zinc-400">
        Vous pouvez demander à être mis en relation avec un conseiller humain à n&apos;importe
        quel moment de l&apos;appel (par exemple : « je veux parler à quelqu&apos;un »).
        L&apos;assistant reconnaît cette demande et transfère l&apos;appel plutôt que
        d&apos;insister pour résoudre lui-même votre demande.
      </p>

      <h2 className="mt-6 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Ce que l&apos;assistant ne décide jamais seul
      </h2>
      <p className="text-zinc-600 dark:text-zinc-400">
        Pour les sujets sensibles — réclamations, litiges, remboursements importants, ou
        toute demande nécessitant un jugement humain — l&apos;assistant escalade
        systématiquement vers un conseiller plutôt que de trancher lui-même.
      </p>

      <h2 className="mt-6 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Confirmation avant toute action engageante
      </h2>
      <p className="text-zinc-600 dark:text-zinc-400">
        Avant de finaliser une réservation, une modification ou une annulation de
        rendez-vous, l&apos;assistant répète les détails et vous demande une confirmation
        orale explicite. Aucune action de ce type n&apos;est effectuée sans votre accord
        clair.
      </p>

      <h2 className="mt-6 text-base font-semibold text-zinc-900 dark:text-zinc-50">
        Limites connues
      </h2>
      <ul className="list-disc pl-5 text-zinc-600 dark:text-zinc-400">
        <li>
          La reconnaissance vocale peut être dégradée par un accent marqué, du bruit de
          fond ou une connexion réseau de mauvaise qualité.
        </li>
        <li>
          L&apos;assistant est conçu pour deux types de demandes (rendez-vous et support) ;
          pour toute autre demande, il vous le signale simplement plutôt que d&apos;inventer
          une réponse.
        </li>
      </ul>

      <p className="mt-8 text-xs text-zinc-400">
        Cette page est un projet de démonstration (portfolio) — le numéro appelé n&apos;est
        pas un service en production.
      </p>
    </div>
  );
}
