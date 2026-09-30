"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";

type Category = Schemas["ExpenseCategoryRead"];
type Kind = Schemas["ExpenseKind"];

/** Familles de charges, fixes ou variables (§ 8.6). Une catégorie n'est pas une écriture. */
export function ExpenseCategoriesDialog({
  open,
  onOpenChange,
  categories,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  categories: readonly Category[];
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("fixed");
  const [error, setError] = useState<string | null>(null);
  const t = labels.finance.expenses;

  const create = useMutation({
    meta: { toastError: false },
    mutationFn: (body: Schemas["ExpenseCategoryCreate"]) =>
      unwrap(api.POST("/api/v1/expense-categories", { body })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.expenseCategories.all });
      toast.success(t.categoryCreated);
      setName("");
      setError(null);
    },
    onError: (caught) => setError(errorMessage(caught)),
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.categoriesTitle}</DialogTitle>
          <DialogDescription>{t.categoryKindHint}</DialogDescription>
        </DialogHeader>
        {categories.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t.noCategories}</p>
        ) : (
          <ul className="max-h-64 divide-y overflow-y-auto rounded-lg border">
            {categories.map((category) => (
              <li key={category.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span>{category.name}</span>
                <Badge variant="neutral">{t.kind[category.kind]}</Badge>
              </li>
            ))}
          </ul>
        )}
        <Can permission="expenses:create">
          <form
            className="grid gap-3 sm:grid-cols-[1fr_8rem_auto] sm:items-end"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              if (!name.trim()) {
                setError(labels.validation.required);
                return;
              }
              create.mutate({ name: name.trim(), kind });
            }}
          >
            <div className="space-y-1.5">
              <Label htmlFor="category-name">{t.categoryName}</Label>
              <Input
                id="category-name"
                value={name}
                maxLength={120}
                onChange={(event) => setName(event.target.value)}
                className="h-9"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="category-kind">{t.categoryKind}</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as Kind)}>
                <SelectTrigger id="category-kind" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fixed">{t.kind.fixed}</SelectItem>
                  <SelectItem value="variable">{t.kind.variable}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.addCategory}
            </Button>
            <div className="sm:col-span-3">
              <FieldError message={error} />
            </div>
          </form>
        </Can>
      </DialogContent>
    </Dialog>
  );
}
