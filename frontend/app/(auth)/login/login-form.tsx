"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { isApiError, errorMessage } from "@/lib/api/errors";
import type { LoginRequest } from "@/lib/api/schema";
import { safeNext } from "@/lib/auth/safe-next";
import { login } from "@/lib/auth/session";
import { labels } from "@/lib/labels";

/** Mêmes bornes que `LoginRequest` côté API ; le serveur revalide de toute façon. */
const loginSchema = z.object({
  company_slug: z
    .string()
    .trim()
    .toLowerCase()
    .regex(/^[a-z0-9-]{3,40}$/, labels.validation.slug),
  email: z.string().trim().pipe(z.email(labels.validation.email)),
  password: z.string().min(1, labels.validation.required).max(128),
}) satisfies z.ZodType<LoginRequest>;

type LoginInput = z.input<typeof loginSchema>;

const LAST_SLUG_KEY = "coges:last-company-slug";

function rememberedSlug(): string {
  try {
    return localStorage.getItem(LAST_SLUG_KEY) ?? "";
  } catch {
    return "";
  }
}

export function LoginForm() {
  const params = useSearchParams();
  const reason = params.get("reason");
  const [formError, setFormError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    setValue,
    setFocus,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<LoginInput, unknown, LoginRequest>({
    resolver: zodResolver(loginSchema),
    defaultValues: { company_slug: "", email: "", password: "" },
  });

  useEffect(() => {
    const slug = rememberedSlug();
    if (slug) {
      setValue("company_slug", slug);
      setFocus("email");
    } else {
      setFocus("company_slug");
    }
  }, [setValue, setFocus]);

  const onSubmit = async (values: LoginRequest) => {
    setFormError(null);
    try {
      await login(values);
    } catch (error) {
      if (isApiError(error) && error.status === 422) {
        for (const field of Object.keys(error.fieldErrors())) {
          if (field in values) {
            setError(field as keyof LoginInput, { message: labels.validation.invalidValue });
          }
        }
      }
      setFormError(errorMessage(error));
      return;
    }
    try {
      localStorage.setItem(LAST_SLUG_KEY, values.company_slug);
    } catch {
      // Stockage indisponible (navigation privée) : simple confort perdu.
    }
    // Rechargement complet vers l'application : `proxy.ts` voit l'indicateur de session.
    window.location.assign(safeNext(params.get("next"), window.location.origin));
  };

  const notice =
    reason === "expired"
      ? labels.login.sessionExpired
      : reason === "logout"
        ? labels.login.loggedOut
        : null;

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      {notice && !formError && (
        <p role="status" className="rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground">
          {notice}
        </p>
      )}
      {formError && (
        <p
          role="alert"
          className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-danger-ink"
        >
          {formError}
        </p>
      )}

      <Field
        id="company_slug"
        label={labels.login.companySlug}
        hint={labels.login.companySlugHint}
        error={errors.company_slug?.message}
      >
        <Input
          id="company_slug"
          autoComplete="organization"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={Boolean(errors.company_slug)}
          aria-describedby="company_slug-hint company_slug-error"
          {...register("company_slug")}
        />
      </Field>

      <Field id="email" label={labels.login.email} error={errors.email?.message}>
        <Input
          id="email"
          type="email"
          autoComplete="username"
          aria-invalid={Boolean(errors.email)}
          aria-describedby="email-error"
          {...register("email")}
        />
      </Field>

      <Field id="password" label={labels.login.password} error={errors.password?.message}>
        <Input
          id="password"
          type="password"
          autoComplete="current-password"
          aria-invalid={Boolean(errors.password)}
          aria-describedby="password-error"
          {...register("password")}
        />
      </Field>

      <Button type="submit" className="w-full" size="lg" disabled={isSubmitting}>
        {isSubmitting ? labels.login.submitting : labels.login.submit}
      </Button>
    </form>
  );
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-xs text-danger-ink">
          {error}
        </p>
      )}
    </div>
  );
}
