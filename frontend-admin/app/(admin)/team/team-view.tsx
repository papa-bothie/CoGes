"use client";

import { History, UserPlus } from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { useMe } from "@/components/admin-shell";
import { ConfirmDialog, type ConfirmRequest } from "@/components/confirm-dialog";
import {
  BUTTON,
  Card,
  Chip,
  EmptyState,
  Notice,
  PageHeader,
  Pill,
  Skeleton,
} from "@/components/ui";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type {
  InvitationIssued,
  ProfileRead,
  TeamInvitation,
  TeamList,
  TeamMember,
  TeamMemberUpdate,
} from "@/lib/api/schema";
import { PLATFORM_ROLE_LABELS, formatDateTime, formatRelative, shortName } from "@/lib/format";
import { withParams } from "@/lib/query";

import { InvitationLink, InviteDialog } from "./invite-dialog";

type Row =
  { kind: "member"; member: TeamMember } | { kind: "invitation"; invitation: TeamInvitation };

const FILTERS = [
  { value: "", label: "Tous" },
  { value: "active", label: "Actifs" },
  { value: "suspended", label: "Suspendus" },
  { value: "invited", label: "Invités" },
];

type Outcome = { tone: "succes" | "danger"; text: string; journal?: string };

function rowsOf(team: TeamList, filter: string): Row[] {
  const members: Row[] = team.members
    .filter((member) =>
      filter === "active"
        ? member.is_active
        : filter === "suspended"
          ? !member.is_active
          : filter !== "invited",
    )
    .map((member) => ({ kind: "member", member }));
  const invitations: Row[] =
    filter === "" || filter === "invited"
      ? team.invitations.map((invitation) => ({ kind: "invitation", invitation }))
      : [];
  return [...invitations, ...members];
}

function StatusPill({ row }: { row: Row }) {
  if (row.kind === "invitation") return <Pill tone="info">Invité</Pill>;
  return row.member.is_active ? (
    <Pill tone="succes">Actif</Pill>
  ) : (
    <Pill tone="danger">Suspendu</Pill>
  );
}

function Seen({ value }: { value: string | null }) {
  if (!value) return <span className="text-encre-douce">Jamais</span>;
  const exact = formatDateTime(value);
  return (
    <time dateTime={value} title={exact}>
      {formatRelative(value)}
      <span className="sr-only"> (le {exact})</span>
    </time>
  );
}

export function TeamView() {
  const me = useMe();
  const pathname = usePathname();
  const params = useSearchParams();
  const filter = params.get("status") ?? "";
  const highlighted = params.get("member");
  const [team, setTeam] = useState<TeamList | null>(null);
  const [profiles, setProfiles] = useState<ProfileRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [inviting, setInviting] = useState(false);
  const [issued, setIssued] = useState<InvitationIssued | null>(null);
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const isAdmin = me?.role === "administrator";

  useEffect(() => {
    unwrap(api.GET("/api/v1/platform/team")).then(setTeam, (caught: unknown) =>
      setError(errorMessage(caught)),
    );
  }, [version]);
  useEffect(() => {
    unwrap(api.GET("/api/v1/platform/roles")).then(setProfiles, () => undefined);
  }, []);

  const reload = () => setVersion((value) => value + 1);

  function done(text: string, journal?: string) {
    setIssued(null);
    setOutcome({ tone: "succes", text, journal });
    reload();
  }

  async function patch(member: TeamMember, body: TeamMemberUpdate) {
    await unwrap(
      api.PATCH("/api/v1/platform/team/{user_id}", {
        params: { path: { user_id: member.id } },
        body,
      }),
    );
  }

  function changeRole(member: TeamMember) {
    const next: TeamMember["role"] = member.role === "administrator" ? "support" : "administrator";
    const name = shortName(member.display_name);
    const label = PLATFORM_ROLE_LABELS[next] ?? next;
    setConfirm({
      title: `Passer ${name} en ${label} ?`,
      consequence:
        next === "administrator" ? (
          <p>
            {name} pourra gérer l&apos;équipe, suspendre une entreprise, changer une offre et lire
            le journal, dès sa prochaine action.
          </p>
        ) : (
          <p>
            {name} ne pourra plus gérer l&apos;équipe ni les abonnements, dès sa prochaine action.
            Il garde la consultation et l&apos;accès support.
          </p>
        ),
      confirmLabel: `Passer ${name} en ${label}`,
      destructive: next === "support",
      onConfirm: async () => {
        await patch(member, { role: next });
        done(`${name} est maintenant ${label}.`, member.id);
      },
    });
  }

  function toggleActive(member: TeamMember) {
    const name = shortName(member.display_name);
    if (member.is_active) {
      setConfirm({
        title: `Suspendre ${name} ?`,
        consequence: (
          <p>
            {name} ne pourra plus se connecter ; ses sessions s&apos;arrêtent à la prochaine
            requête. Son compte et son historique sont conservés.
          </p>
        ),
        confirmLabel: `Suspendre ${name}`,
        destructive: true,
        requireReason: true,
        onConfirm: async (reason) => {
          await patch(member, { is_active: false, reason });
          done(`${name} est suspendu.`, member.id);
        },
      });
    } else {
      setConfirm({
        title: `Réactiver ${name} ?`,
        consequence: <p>{name} pourra de nouveau se connecter avec son mot de passe.</p>,
        confirmLabel: `Réactiver ${name}`,
        onConfirm: async () => {
          await patch(member, { is_active: true });
          done(`${name} est réactivé.`, member.id);
        },
      });
    }
  }

  function cancelInvitation(invitation: TeamInvitation) {
    const name = shortName(invitation.display_name);
    setConfirm({
      title: `Annuler l'invitation de ${name} ?`,
      consequence: <p>Le lien envoyé à {invitation.email} ne servira plus.</p>,
      confirmLabel: `Annuler l'invitation de ${name}`,
      destructive: true,
      onConfirm: async () => {
        await unwrap(
          api.DELETE("/api/v1/platform/team/invitations/{invitation_id}", {
            params: { path: { invitation_id: invitation.id } },
          }),
        );
        done(`L'invitation de ${name} est annulée.`, invitation.id);
      },
    });
  }

  async function resend(invitation: TeamInvitation) {
    try {
      const result = await unwrap(
        api.POST("/api/v1/platform/team/invitations/{invitation_id}/resend", {
          params: { path: { invitation_id: invitation.id } },
        }),
      );
      setOutcome({
        tone: "succes",
        text: result.email_sent
          ? `Nouveau lien envoyé à ${invitation.email}, valable 72 heures.`
          : `Nouveau lien créé pour ${invitation.email}.`,
        journal: invitation.id,
      });
      setIssued(result.invitation_url ? result : null);
      reload();
    } catch (caught) {
      setOutcome({ tone: "danger", text: errorMessage(caught) });
    }
  }

  function actions(row: Row): ReactNode {
    if (!isAdmin) return null;
    if (row.kind === "invitation") {
      return (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => void resend(row.invitation)}
            className={BUTTON.secondary}
          >
            Renvoyer
            <span className="sr-only"> l&apos;invitation de {row.invitation.display_name}</span>
          </button>
          <button
            type="button"
            onClick={() => cancelInvitation(row.invitation)}
            className={BUTTON.quiet}
          >
            Annuler
            <span className="sr-only"> l&apos;invitation de {row.invitation.display_name}</span>
          </button>
        </div>
      );
    }
    const member = row.member;
    if (member.is_me) {
      return (
        <p className="max-w-56 text-sm text-encre-douce">
          C&apos;est votre compte : un autre administrateur peut changer votre profil ou le
          suspendre.
        </p>
      );
    }
    return (
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => changeRole(member)} className={BUTTON.secondary}>
          Changer le profil<span className="sr-only"> de {member.display_name}</span>
        </button>
        <button
          type="button"
          onClick={() => toggleActive(member)}
          className={member.is_active ? BUTTON.quiet : BUTTON.secondary}
        >
          {member.is_active ? "Suspendre" : "Réactiver"}
          <span className="sr-only"> {member.display_name}</span>
        </button>
      </div>
    );
  }

  function history(id: string, name: string): ReactNode {
    if (!isAdmin) return null;
    return (
      <Link
        href={`/audit?entity=${id}`}
        className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold underline"
      >
        <History aria-hidden="true" className="size-4" />
        Historique<span className="sr-only"> de {name}</span>
      </Link>
    );
  }

  const rows = team ? rowsOf(team, filter) : [];
  const idOf = (row: Row) => (row.kind === "member" ? row.member.id : row.invitation.id);

  return (
    <section aria-labelledby="titre-equipe" className="space-y-5">
      <PageHeader
        id="titre-equipe"
        title="Équipe"
        description="Les comptes de l'équipe CoGes et les invitations en attente."
        actions={
          isAdmin && (
            <button type="button" onClick={() => setInviting(true)} className={BUTTON.primary}>
              <UserPlus aria-hidden="true" className="size-5" />
              Inviter un collègue
            </button>
          )
        }
      />

      {outcome && (
        <Notice tone={outcome.tone}>
          {outcome.text}{" "}
          {outcome.journal && isAdmin && (
            <Link href={`/audit?entity=${outcome.journal}`} className="font-semibold underline">
              Voir dans le journal
            </Link>
          )}
        </Notice>
      )}
      {issued?.invitation_url && (
        <InvitationLink url={issued.invitation_url} email={issued.invitation.email} />
      )}
      {error && <Notice tone="danger">{error}</Notice>}

      <div className="flex flex-wrap gap-2" role="group" aria-label="Statut">
        {FILTERS.map((option) => (
          <Chip
            key={option.label}
            href={withParams(pathname, params, { status: option.value || null, member: null })}
            active={filter === option.value}
          >
            {option.label}
          </Chip>
        ))}
      </div>

      {!team && !error && <Skeleton label="Chargement de l'équipe" />}
      {team && rows.length === 0 && (
        <EmptyState title="Personne dans ce filtre.">
          {isAdmin
            ? "Invitez un collègue avec le bouton ci-dessus."
            : "Choisissez un autre filtre."}
        </EmptyState>
      )}
      {team && rows.length > 0 && (
        <>
          <div className="hidden overflow-x-auto rounded-xl border border-trait bg-surface md:block">
            <table className="w-full text-left">
              <thead className="border-b border-trait text-sm text-encre-douce">
                <tr>
                  <th scope="col" className="px-4 py-3">
                    Nom
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Profil
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Statut
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Dernière connexion
                  </th>
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const name =
                    row.kind === "member" ? row.member.display_name : row.invitation.display_name;
                  const email = row.kind === "member" ? row.member.email : row.invitation.email;
                  const role = row.kind === "member" ? row.member.role : row.invitation.role;
                  return (
                    <tr
                      key={idOf(row)}
                      aria-current={highlighted === idOf(row) ? "true" : undefined}
                      className={`border-b border-trait align-top last:border-0 ${highlighted === idOf(row) ? "bg-voile" : ""}`}
                    >
                      <td className="px-4 py-3">
                        <span className="block font-semibold">
                          {name}
                          {row.kind === "member" && row.member.is_me && (
                            <span className="ml-2 text-sm font-normal text-encre-douce">
                              (vous)
                            </span>
                          )}
                        </span>
                        <span className="block text-sm text-encre-douce">{email}</span>
                        {history(idOf(row), name)}
                      </td>
                      <td className="px-4 py-3">{PLATFORM_ROLE_LABELS[role] ?? role}</td>
                      <td className="px-4 py-3">
                        <StatusPill row={row} />
                      </td>
                      <td className="px-4 py-3">
                        {row.kind === "member" ? (
                          <Seen value={row.member.last_login_at} />
                        ) : (
                          <span className="text-sm text-encre-douce">
                            Lien valable jusqu&apos;au {formatDateTime(row.invitation.expires_at)}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">{actions(row)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ul aria-label="Comptes de l'équipe" className="space-y-3 md:hidden">
            {rows.map((row) => {
              const name =
                row.kind === "member" ? row.member.display_name : row.invitation.display_name;
              const email = row.kind === "member" ? row.member.email : row.invitation.email;
              const role = row.kind === "member" ? row.member.role : row.invitation.role;
              return (
                <li
                  key={idOf(row)}
                  className="space-y-2 rounded-xl border border-trait bg-surface p-4"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-semibold">{name}</p>
                      <p className="truncate text-sm text-encre-douce">{email}</p>
                    </div>
                    <StatusPill row={row} />
                  </div>
                  <p>
                    {PLATFORM_ROLE_LABELS[role] ?? role} ·{" "}
                    {row.kind === "member" ? (
                      <Seen value={row.member.last_login_at} />
                    ) : (
                      `lien valable jusqu'au ${formatDateTime(row.invitation.expires_at)}`
                    )}
                  </p>
                  {history(idOf(row), name)}
                  {actions(row)}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {profiles && (
        <Card aria-labelledby="titre-profils" className="space-y-4">
          <h2 id="titre-profils" className="text-lg font-bold">
            Ce que peut chaque profil
          </h2>
          <div className="grid gap-6 md:grid-cols-2">
            {profiles.map((profile) => (
              <div key={profile.role} className="space-y-2">
                <h3 className="font-bold">{profile.label}</h3>
                <p className="text-encre-douce">{profile.description}</p>
                <ul className="list-disc space-y-0.5 pl-5">
                  {profile.capabilities.map((capability) => (
                    <li key={capability.key}>{capability.label}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}

      <InviteDialog
        open={inviting}
        onClose={() => setInviting(false)}
        onInvited={(result) => {
          setInviting(false);
          setIssued(result.invitation_url ? result : null);
          setOutcome({
            tone: "succes",
            text: result.email_sent
              ? `Invitation envoyée à ${result.invitation.email}.`
              : `Invitation créée pour ${result.invitation.email}.`,
            journal: result.invitation.id,
          });
          reload();
        }}
      />
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </section>
  );
}
