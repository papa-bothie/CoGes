"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { fieldClasses } from "@/components/kit/rubrique";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Can, usePermission } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { flattenTree, useCategories, type CategoryNode } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { SHELF_COLORS, shelfClass } from "@/lib/shelf-colors";
import { cn } from "@/lib/utils";

const t = labels.stockScreens.shelves;
const COUNTS_KEY = [...queryKeys.categories.all, "counts"] as const;

const ICON_BUTTON = cn(
  "inline-flex size-12 shrink-0 items-center justify-center rounded-[14px] border-2 border-input bg-card text-foreground",
  "outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50",
  "disabled:pointer-events-none disabled:text-muted-foreground disabled:opacity-60",
);

/**
 * L'écran Rayons de la maquette v2 (12) : ajouter un rayon (nom et une couleur parmi
 * huit), renommer sur place, supprimer seulement un rayon vide. Les sous-rayons déjà
 * créés restent affichés sous leur parent, avec leur chemin ; on n'en crée plus d'ici
 * (ADR 0071). Le serveur garde le dernier mot : doublon et rayon non vide sont refusés.
 */
export function CategoriesView() {
  const categories = useCategories();
  const counts = useQuery({
    queryKey: COUNTS_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/products/category-counts")),
  });
  const shelves = useMemo(() => flattenTree(categories.data ?? []), [categories.data]);
  const countOf = useMemo(() => {
    const byId = new Map((counts.data?.items ?? []).map((row) => [row.category_id, row]));
    return (id: string) => byId.get(id)?.product_count ?? 0;
  }, [counts.data]);
  const hasChildren = useMemo(
    () => new Set(shelves.map((shelf) => shelf.parent_id).filter(Boolean)),
    [shelves],
  );
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<CategoryNode | null>(null);

  return (
    <div className="mx-auto flex max-w-[932px] flex-col gap-5">
      <Link
        href="/products"
        className="inline-flex min-h-11 items-center gap-2 self-start font-bold text-foreground hover:underline pointer-coarse:min-h-12"
      >
        <ArrowLeft className="size-[22px]" aria-hidden />
        {t.back}
      </Link>
      <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>

      <Can permission="categories:create">
        <NewShelf />
      </Can>

      {categories.isError ? (
        <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
      ) : !categories.data ? (
        <Skeleton className="h-64 w-full rounded-carte" />
      ) : shelves.length === 0 ? (
        <p className="rounded-carte border border-border bg-card px-5 py-10 text-center text-lg">
          {t.empty}
        </p>
      ) : (
        <ul aria-label={t.title} className="flex flex-col gap-2.5">
          {shelves.map((shelf) => (
            <ShelfRow
              key={shelf.id}
              shelf={shelf}
              count={countOf(shelf.id)}
              locked={!counts.data || countOf(shelf.id) > 0 || hasChildren.has(shelf.id)}
              renaming={renaming === shelf.id}
              onRename={() => setRenaming(shelf.id)}
              onRenamed={() => setRenaming(null)}
              onDelete={() => setDeleting(shelf)}
            />
          ))}
        </ul>
      )}
      <p className="text-base text-muted-foreground">{t.locked}</p>

      <DeleteDialog shelf={deleting} onClose={() => setDeleting(null)} />
    </div>
  );
}

function NewShelf() {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [color, setColor] = useState<number>(5);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      unwrap(api.POST("/api/v1/categories", { body: { name: name.trim(), color } })),
    onSuccess: (shelf) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.categories.all });
      toast.success(t.created(shelf.name));
      setName("");
      setError(null);
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <form
      noValidate
      className="flex flex-col gap-3.5 rounded-carte border border-border bg-card p-[22px]"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <label htmlFor="new-shelf" className="text-[17px] font-bold">
        {t.newLabel}
      </label>
      <div className="flex flex-wrap gap-2.5">
        <input
          id="new-shelf"
          value={name}
          maxLength={120}
          autoComplete="off"
          placeholder={t.placeholder}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "new-shelf-error" : undefined}
          onChange={(event) => setName(event.target.value)}
          className={cn(fieldClasses("stock"), "min-h-14 flex-[1_1_220px] px-4 text-lg")}
        />
        <button
          type="submit"
          disabled={!name.trim() || create.isPending}
          className={cn(
            "min-h-14 rounded-bouton bg-stock px-5 text-[17px] font-bold text-blanc outline-none",
            "hover:bg-stock/90 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:bg-stock/45",
          )}
        >
          {t.add}
        </button>
      </div>
      <div role="radiogroup" aria-label={t.colors} className="flex flex-wrap gap-2.5">
        {SHELF_COLORS.map((entry) => (
          <button
            key={entry.value}
            type="button"
            role="radio"
            aria-checked={color === entry.value}
            aria-label={entry.label}
            onClick={() => setColor(entry.value)}
            className={cn(
              "size-12 rounded-full border-[3px] border-transparent outline-none",
              "focus-visible:ring-3 focus-visible:ring-ring/50",
              color === entry.value && "border-foreground shadow-[inset_0_0_0_3px_var(--card)]",
              entry.className,
            )}
          />
        ))}
      </div>
      <FieldError id="new-shelf-error" message={error} />
    </form>
  );
}

function ShelfRow({
  shelf,
  count,
  locked,
  renaming,
  onRename,
  onRenamed,
  onDelete,
}: {
  shelf: CategoryNode;
  count: number;
  locked: boolean;
  renaming: boolean;
  onRename: () => void;
  onRenamed: () => void;
  onDelete: () => void;
}) {
  const canDelete = usePermission("categories:delete");
  return (
    <li
      className="flex items-center gap-3.5 rounded-[18px] border border-border bg-card p-3.5"
      style={{ marginLeft: shelf.depth ? `${shelf.depth * 28}px` : undefined }}
    >
      <span
        aria-hidden
        className={cn(
          "flex size-[52px] shrink-0 items-center justify-center rounded-touche text-xl font-extrabold text-blanc",
          shelfClass(shelf),
        )}
      >
        {shelf.name.trim().charAt(0).toUpperCase()}
      </span>
      {renaming ? (
        <RenameForm shelf={shelf} onDone={onRenamed} />
      ) : (
        <>
          <span className="min-w-0 flex-1">
            <span className="block text-lg font-bold">{shelf.depth ? shelf.path : shelf.name}</span>
            <span className="block text-muted-foreground">{t.count(count)}</span>
          </span>
          <Can permission="categories:update">
            <button
              type="button"
              className={ICON_BUTTON}
              aria-label={t.rename(shelf.name)}
              onClick={onRename}
            >
              <Pencil className="size-[22px]" aria-hidden />
            </button>
          </Can>
          {canDelete && (
            <button
              type="button"
              className={cn(ICON_BUTTON, "text-depenses-encre")}
              aria-label={t.remove(shelf.name)}
              disabled={locked}
              onClick={onDelete}
            >
              <Trash2 className="size-[22px]" aria-hidden />
            </button>
          )}
        </>
      )}
    </li>
  );
}

function RenameForm({ shelf, onDone }: { shelf: CategoryNode; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(shelf.name);
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      unwrap(
        api.PATCH("/api/v1/categories/{category_id}", {
          params: { path: { category_id: shelf.id } },
          body: { name: name.trim() },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.categories.all });
      toast.success(t.renamed);
      onDone();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });
  const errorId = `rename-${shelf.id}-error`;

  return (
    <form
      noValidate
      className="flex min-w-0 flex-1 flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        if (!name.trim()) return;
        if (name.trim() === shelf.name) onDone();
        else save.mutate();
      }}
    >
      <div className="flex flex-wrap gap-2">
        <input
          autoFocus
          value={name}
          maxLength={120}
          aria-label={t.renameField(shelf.name)}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => event.key === "Escape" && onDone()}
          className={cn(fieldClasses("stock"), "min-h-12 flex-[1_1_180px] px-3.5 text-lg")}
        />
        <Button type="submit" size="standard" disabled={!name.trim() || save.isPending}>
          {t.save}
        </Button>
        <Button type="button" size="standard" variant="outline" onClick={onDone}>
          {t.cancel}
        </Button>
      </div>
      <FieldError id={errorId} message={error} />
    </form>
  );
}

function DeleteDialog({ shelf, onClose }: { shelf: CategoryNode | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const remove = useMutation({
    meta: { toastError: false },
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/v1/categories/{category_id}", { params: { path: { category_id: id } } }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.categories.all });
      toast.success(t.removed);
      onClose();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Dialog
      open={shelf !== null}
      onOpenChange={(open) => {
        if (!open) {
          setError(null);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{shelf && t.removeTitle(shelf.name)}</DialogTitle>
          <DialogDescription>{t.removeHint}</DialogDescription>
        </DialogHeader>
        <FieldError message={error} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t.cancel}
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending || !shelf}
            onClick={() => shelf && remove.mutate(shelf.id)}
          >
            {labels.common.delete}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
