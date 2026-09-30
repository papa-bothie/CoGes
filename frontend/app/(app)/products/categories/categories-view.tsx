"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FolderPlus, FolderTree, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FieldError } from "@/components/field-error";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { flattenTree, useCategories, type CategoryNode } from "@/lib/api/queries/categories";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";

const ROOT = "root";

type Editing =
  { mode: "create"; parentId: string | null } | { mode: "edit"; node: CategoryNode } | null;

/** Arbre des catégories. Les refus (doublon, cycle, catégorie non vide) viennent du serveur. */
export function CategoriesView() {
  const categories = useCategories();
  const tree = useMemo(() => flattenTree(categories.data ?? []), [categories.data]);
  const [editing, setEditing] = useState<Editing>(null);
  const [deleting, setDeleting] = useState<CategoryNode | null>(null);

  return (
    <>
      <Link
        href="/products"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden />
        {labels.categories.backToProducts}
      </Link>
      <PageHeader
        title={labels.categories.title}
        count={categories.data ? labels.categories.count(categories.data.length) : undefined}
        actions={
          <Can permission="categories:create">
            <Button onClick={() => setEditing({ mode: "create", parentId: null })}>
              <Plus aria-hidden />
              {labels.categories.add}
            </Button>
          </Can>
        }
      />
      {categories.isError ? (
        <ErrorState error={categories.error} onRetry={() => void categories.refetch()} />
      ) : !categories.data ? (
        <Skeleton className="h-64 w-full" />
      ) : tree.length === 0 ? (
        <EmptyState icon={FolderTree} title={labels.categories.empty} />
      ) : (
        <Card className="py-2">
          <ul role="tree" aria-label={labels.categories.title}>
            {tree.map((node) => (
              <li
                key={node.id}
                role="treeitem"
                aria-level={node.depth + 1}
                aria-selected={false}
                className="group flex items-center justify-between gap-3 px-4 py-2 hover:bg-muted/50"
                style={{ paddingLeft: `${16 + node.depth * 24}px` }}
              >
                <span className="flex items-center gap-2">
                  <FolderTree className="size-4 text-muted-foreground" aria-hidden />
                  <Link
                    href={`/products?category=${node.id}`}
                    className="font-medium hover:underline"
                  >
                    {node.name}
                  </Link>
                </span>
                <span className="flex items-center gap-1 opacity-70 group-hover:opacity-100">
                  <Can permission="categories:create">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={labels.categories.addChild(node.name)}
                      onClick={() => setEditing({ mode: "create", parentId: node.id })}
                    >
                      <FolderPlus />
                    </Button>
                  </Can>
                  <Can permission="categories:update">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={labels.categories.rename(node.name)}
                      onClick={() => setEditing({ mode: "edit", node })}
                    >
                      <Pencil />
                    </Button>
                  </Can>
                  <Can permission="categories:delete">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={labels.categories.remove(node.name)}
                      onClick={() => setDeleting(node)}
                    >
                      <Trash2 />
                    </Button>
                  </Can>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {editing && <CategoryDialog editing={editing} tree={tree} onClose={() => setEditing(null)} />}
      <DeleteDialog node={deleting} onClose={() => setDeleting(null)} />
    </>
  );
}

function CategoryDialog({
  editing,
  tree,
  onClose,
}: {
  editing: NonNullable<Editing>;
  tree: readonly CategoryNode[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const initial = editing.mode === "edit" ? editing.node : null;
  const [name, setName] = useState(initial?.name ?? "");
  const [parent, setParent] = useState(
    (editing.mode === "edit" ? editing.node.parent_id : editing.parentId) ?? ROOT,
  );
  const [error, setError] = useState<string | null>(null);

  // Une catégorie ne peut pas descendre sous elle-même ni sous ses descendants.
  const parents = initial
    ? tree.filter((node) => node.id !== initial.id && !node.path.startsWith(`${initial.path} › `))
    : tree;

  const save = useMutation({
    meta: { toastError: false },
    mutationFn: () => {
      const body = { name: name.trim(), parent_id: parent === ROOT ? null : parent };
      return initial
        ? unwrap(
            api.PATCH("/api/v1/categories/{category_id}", {
              params: { path: { category_id: initial.id } },
              body,
            }),
          )
        : unwrap(api.POST("/api/v1/categories", { body }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.categories.all });
      toast.success(initial ? labels.categories.saved : labels.categories.created);
      onClose();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {initial ? labels.categories.editTitle : labels.categories.createTitle}
          </DialogTitle>
        </DialogHeader>
        <form
          noValidate
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (!name.trim()) {
              setError(labels.validation.required);
              return;
            }
            setError(null);
            save.mutate();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="category-name">{labels.categories.name}</Label>
            <Input
              id="category-name"
              value={name}
              maxLength={120}
              aria-invalid={Boolean(error)}
              aria-describedby={error ? "category-error" : undefined}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="category-parent">{labels.categories.parent}</Label>
            <Select value={parent} onValueChange={setParent}>
              <SelectTrigger id="category-parent" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ROOT}>{labels.categories.root}</SelectItem>
                {parents.map((node) => (
                  <SelectItem key={node.id} value={node.id}>
                    <span style={{ paddingLeft: `${node.depth * 12}px` }}>{node.name}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <FieldError id="category-error" message={error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              {labels.common.close}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {labels.common.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteDialog({ node, onClose }: { node: CategoryNode | null; onClose: () => void }) {
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
      toast.success(labels.categories.deleted);
      onClose();
    },
    onError: (failure) => setError(errorMessage(failure)),
  });

  return (
    <Dialog
      open={node !== null}
      onOpenChange={(open) => {
        if (!open) {
          setError(null);
          onClose();
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{labels.categories.deleteTitle}</DialogTitle>
          <DialogDescription>
            {node && labels.categories.deleteDescription(node.name)}
          </DialogDescription>
        </DialogHeader>
        <FieldError message={error} />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {labels.common.close}
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending || !node}
            onClick={() => node && remove.mutate(node.id)}
          >
            {labels.common.delete}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
