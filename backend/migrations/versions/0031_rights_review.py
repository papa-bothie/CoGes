"""Droits après la relecture des lots 28 et 29 (prompt 32, bloc D, ADR 0103).

Révision de **données** seulement, aucun schéma :

- **D1** : `payments:create` n'est plus donné par « Vendre ». Il est retiré de tout rôle qui
  ne le tient que par là : ni « Encaisser une dette » (`debts:read`), ni « Gérer les dettes,
  les dépenses et les paiements » (`payments:update`). Un rôle où le gérant a coché
  « Encaisser une dette » garde tout. La caisse encaisse par la confirmation d'une vente.
- **D3** : `company:update` et `system:read` sont réservés au gérant depuis l'ADR 0099 ; un
  rôle autre que le gérant système qui les porte encore (réglé avant) les perd.

Chaque rôle touché reçoit une ligne d'**audit critique** (`roles`, `update`, auteur NULL,
`diff.source = "0031"`, droits avant et après). Le `downgrade` remet exactement les droits
retirés, relus dans ces lignes ; le journal, append-only, garde la trace des deux sens.

Les tables d'entreprise sont sous RLS FORCE : la révision parcourt les entreprises en posant
`app.company_id` pour chacune (`set_config(…, true)`, transaction de la révision), comme
l'API ; seule `companies` est lue sans FORCE, le temps d'en lister les identifiants.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOR_EACH_COMPANY = """
DO $$
DECLARE
   v_company uuid;
   v_companies uuid[];
   v_role record;
BEGIN
   ALTER TABLE companies NO FORCE ROW LEVEL SECURITY;
   SELECT coalesce(array_agg(id), '{{}}') INTO v_companies FROM companies;
   ALTER TABLE companies FORCE ROW LEVEL SECURITY;
   FOREACH v_company IN ARRAY v_companies LOOP
      PERFORM set_config('app.company_id', v_company::text, true);
      {body}
   END LOOP;
END $$
"""

_UPGRADE_BODY = """
      FOR v_role IN
         SELECT r.id,
                array(SELECT p.code FROM role_permissions rp
                        JOIN permissions p ON p.id = rp.permission_id
                       WHERE rp.company_id = r.company_id AND rp.role_id = r.id
                       ORDER BY p.code) AS before,
                array(SELECT p.code FROM role_permissions rp
                        JOIN permissions p ON p.id = rp.permission_id
                       WHERE rp.company_id = r.company_id AND rp.role_id = r.id
                         AND (   p.code IN ('company:update', 'system:read')
                              OR (p.code = 'payments:create'
                                  AND NOT EXISTS (
                                     SELECT 1 FROM role_permissions o
                                       JOIN permissions q ON q.id = o.permission_id
                                      WHERE o.company_id = r.company_id AND o.role_id = r.id
                                        AND q.code IN ('debts:read', 'payments:update'))))
                       ORDER BY p.code) AS removed
           FROM roles r
          WHERE r.company_id = v_company
            AND NOT (r.is_system AND r.name = 'gerant')
      LOOP
         CONTINUE WHEN cardinality(v_role.removed) = 0;
         DELETE FROM role_permissions rp
          USING permissions p
          WHERE rp.company_id = v_company AND rp.role_id = v_role.id
            AND p.id = rp.permission_id AND p.code = ANY (v_role.removed);
         INSERT INTO audit_logs (company_id, actor_user_id, action, entity_table, entity_id, diff)
         VALUES (v_company, NULL, 'update', 'roles', v_role.id,
                 jsonb_build_object(
                    'source', '0031',
                    'reason', 'ADR 0103 : droits réservés ou donnés par « Vendre »',
                    'removed', to_jsonb(v_role.removed),
                    'before', jsonb_build_object('permissions', to_jsonb(v_role.before)),
                    'after', jsonb_build_object('permissions', to_jsonb(array(
                       SELECT unnest(v_role.before) EXCEPT SELECT unnest(v_role.removed)
                       ORDER BY 1)))));
      END LOOP;
"""

_DOWNGRADE_BODY = """
      FOR v_role IN
         SELECT entity_id AS id, diff->'removed' AS removed
           FROM audit_logs
          WHERE company_id = v_company AND entity_table = 'roles'
            AND diff->>'source' = '0031'
      LOOP
         INSERT INTO role_permissions (company_id, role_id, permission_id)
         SELECT v_company, v_role.id, p.id
           FROM permissions p
          WHERE p.code IN (SELECT jsonb_array_elements_text(v_role.removed))
            AND EXISTS (SELECT 1 FROM roles r WHERE r.company_id = v_company AND r.id = v_role.id)
         ON CONFLICT DO NOTHING;
         INSERT INTO audit_logs (company_id, actor_user_id, action, entity_table, entity_id, diff)
         VALUES (v_company, NULL, 'update', 'roles', v_role.id,
                 jsonb_build_object('source', '0031-downgrade', 'restored', v_role.removed));
      END LOOP;
"""


def upgrade() -> None:
    op.execute(_FOR_EACH_COMPANY.format(body=_UPGRADE_BODY))


def downgrade() -> None:
    op.execute(_FOR_EACH_COMPANY.format(body=_DOWNGRADE_BODY))
