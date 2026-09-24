import Link from "next/link";

const LINKS = [
  { href: "/", label: "Vue d'ensemble" },
  { href: "/rendez-vous", label: "Rendez-vous" },
  { href: "/tickets", label: "Tickets" },
  { href: "/transparence", label: "Transparence" },
];

export function NavBar() {
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-6 px-6 py-4">
        <span className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-50">
          Allo-IA <span className="font-normal text-zinc-400">— admin</span>
        </span>
        <nav className="flex gap-5 text-sm text-zinc-600 dark:text-zinc-400">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="transition-colors hover:text-zinc-950 dark:hover:text-zinc-50"
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  );
}
