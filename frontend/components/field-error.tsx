/** Erreur rattachée à un champ : annoncée par les lecteurs d'écran, en rouge sous le champ. */
export function FieldError({ id, message }: { id?: string; message?: string | null }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="text-sm text-danger-ink">
      {message}
    </p>
  );
}
