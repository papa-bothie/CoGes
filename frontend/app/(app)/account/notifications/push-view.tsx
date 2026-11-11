"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, BellOff } from "lucide-react";
import { useEffect, useState } from "react";

import { FieldError } from "@/components/field-error";
import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/queries/keys";
import { labels } from "@/lib/labels";
import { disablePush, enablePush, pushState, type PushState } from "@/lib/push";

const t = labels.push;

/**
 * « Notifications sur le téléphone » (prompt 36, bloc N, ADR 0120), depuis le menu du compte.
 * La permission du navigateur n'est demandée qu'à l'appui sur « Activer ». Chaque cas a sa
 * phrase : iPhone sans installation, refus du navigateur, navigateur incapable.
 */
export function PushView() {
  const queryClient = useQueryClient();
  const config = useQuery({
    queryKey: queryKeys.notifications.pushConfig,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/push/config")),
  });
  const devices = useQuery({
    queryKey: queryKeys.notifications.pushDevices,
    queryFn: () => unwrap(api.GET("/api/v1/notifications/push/subscriptions")),
  });
  const publicKey = config.data?.public_key ?? null;
  const [state, setState] = useState<PushState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config.isSuccess) return;
    let live = true;
    void pushState(publicKey).then((found) => {
      if (live) setState(found);
    });
    return () => {
      live = false;
    };
  }, [config.isSuccess, publicKey]);

  const refreshDevices = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.notifications.pushDevices });

  const enable = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      enablePush(publicKey!, (body) =>
        unwrap(api.POST("/api/v1/notifications/push/subscriptions", { body })),
      ),
    onMutate: () => setError(null),
    onSuccess: (found) => {
      setState(found);
      void refreshDevices();
    },
    onError: () => setError(t.failed),
  });

  const disable = useMutation({
    meta: { toastError: false },
    mutationFn: () =>
      disablePush((endpoint) =>
        unwrap(api.POST("/api/v1/notifications/push/subscriptions/remove", { body: { endpoint } })),
      ),
    onMutate: () => setError(null),
    onSuccess: () => {
      setState("off");
      void refreshDevices();
    },
    onError: () => setError(t.failed),
  });

  const count = devices.data?.items.length ?? 0;

  return (
    <div className="mx-auto flex max-w-[560px] flex-col gap-5">
      <div>
        <h1 className="text-titre-page leading-[1.45] tracking-[-0.01em]">{t.title}</h1>
        <p className="text-lg text-muted-foreground">{t.intro}</p>
      </div>

      <section
        aria-live="polite"
        className="flex flex-col gap-4 rounded-carte border border-border bg-card p-carte"
      >
        {state === null && <p className="text-muted-foreground">…</p>}
        {state === "unavailable" && <p>{t.unavailable}</p>}
        {state === "unsupported" && <p>{t.unsupported}</p>}
        {state === "needs-install" && (
          <>
            <p className="font-bold">{t.needsInstall}</p>
            <p>{t.installSteps}</p>
          </>
        )}
        {state === "denied" && <p role="status">{t.denied}</p>}

        {state === "on" && (
          <>
            <p role="status" className="flex items-center gap-2.5 font-bold text-ventes-encre">
              <BellRing className="size-6 shrink-0" aria-hidden /> {t.on}
            </p>
            <Button
              variant="secondaire"
              size="standard"
              className="text-lg"
              disabled={disable.isPending}
              onClick={() => disable.mutate()}
            >
              {t.disable}
            </Button>
          </>
        )}

        {state === "off" && (
          <>
            <p className="flex items-center gap-2.5">
              <BellOff className="size-6 shrink-0 text-muted-foreground" aria-hidden /> {t.off}
            </p>
            <Button
              variant="ventes"
              size="standard"
              className="text-lg"
              disabled={enable.isPending || !publicKey}
              onClick={() => enable.mutate()}
            >
              {t.enable}
            </Button>
            {enable.isPending && <p className="text-muted-foreground">{t.asking}</p>}
          </>
        )}

        <FieldError message={error} />
        {count > 0 && <p className="text-sm text-muted-foreground">{t.devices(count)}</p>}
      </section>
    </div>
  );
}
