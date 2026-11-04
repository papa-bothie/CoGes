"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { FieldError } from "@/components/field-error";
import { ChoiceGroup } from "@/components/kit/choice-group";
import { fieldClasses } from "@/components/kit/rubrique";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Can } from "@/hooks/use-permission";
import { api, unwrap } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import { queryKeys } from "@/lib/api/queries/keys";
import type { Schemas } from "@/lib/api/schema";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

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
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t.categoriesTitle}</DialogTitle>
          <DialogDescription>{t.categoryKindHint}</DialogDescription>
        </DialogHeader>
        {categories.length === 0 ? (
          <p className="text-corps text-muted-foreground">{t.noCategories}</p>
        ) : (
          <ul aria-label={t.categoriesTitle} className="max-h-64 overflow-y-auto">
            {categories.map((category) => (
              <li
                key={category.id}
                className="flex min-h-cible items-center justify-between gap-3 border-t border-filet py-2 text-corps first:border-t-0"
              >
                <span className="font-bold">{category.name}</span>
                <Badge variant="neutral">{t.kind[category.kind]}</Badge>
              </li>
            ))}
          </ul>
        )}
        <Can permission="expenses:create">
          <form
            className="flex flex-col gap-5 border-t border-filet pt-5"
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
            <div>
              <label htmlFor="category-name" className="mb-2 block text-libelle">
                {t.categoryName}
              </label>
              <input
                id="category-name"
                value={name}
                maxLength={120}
                autoComplete="off"
                aria-invalid={error ? true : undefined}
                onChange={(event) => setName(event.target.value)}
                className={cn(fieldClasses("depenses"), "min-h-[58px] px-4 text-[19px]")}
              />
            </div>
            <div>
              <p className="mb-2 text-libelle">{t.categoryKind}</p>
              <ChoiceGroup
                label={t.categoryKind}
                rubrique="depenses"
                value={kind}
                onValueChange={setKind}
                choices={[
                  { value: "fixed", label: t.kind.fixed },
                  { value: "variable", label: t.kind.variable },
                ]}
              />
            </div>
            <FieldError message={error} />
            <Button type="submit" variant="depenses" size="standard" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" aria-hidden />}
              {t.addCategory}
            </Button>
          </form>
        </Can>
      </DialogContent>
    </Dialog>
  );
}
