"use client";

import { ScanBarcode } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

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
import { FORMATS, loadDetector } from "@/lib/barcode/detector";
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/** Rien de lu au bout de ce délai : un conseil s'affiche (prompt 33). */
const HELP_AFTER_MS = 10_000;

type Camera = "off" | "preparing" | "on";

/**
 * « Scanner le code-barres » (ADR 0066, 0106) : la caméra par l'API native du navigateur, ou
 * par la bibliothèque de lecture là où elle manque (iPhone, Firefox) ; le champ reçoit en
 * secours ce que tape une douchette, ou le clavier. La caméra s'éteint dès qu'un code est lu,
 * que la fenêtre se ferme ou que l'onglet est caché.
 */
export function BarcodeScanButton({
  onScan,
  tile = false,
  label,
  variant = "secondaire",
  className,
  restoreFocus = true,
}: {
  onScan: (code: string) => void;
  /** Grande tuile en pointillés de la maquette 09, au lieu d'un bouton. */
  tile?: boolean;
  /** Texte du bouton ; « Scanner le code-barres » par défaut. */
  label?: ReactNode;
  variant?: "secondaire" | "stock";
  className?: string;
  /** Faux : après un code lu, le focus va où l'écran le place (la quantité reçue). */
  restoreFocus?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [camera, setCamera] = useState<Camera>("off");
  const [help, setHelp] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const scanned = useRef(false);
  const inputId = useId();
  const t = labels.products.newForm;

  useEffect(() => {
    if (!open) return;
    if (!navigator.mediaDevices?.getUserMedia) return;
    let stream: MediaStream | null = null;
    let timer: number | undefined;
    let helpTimer: number | undefined;
    let stopped = false;
    let busy = false;
    // La vidéo de la fenêtre n'existe qu'une fois la fenêtre montée : lue après la caméra.
    let video: HTMLVideoElement | null = null;
    // Onglet caché (téléphone posé, autre application) : la fenêtre se ferme, la caméra avec.
    const onHidden = () => {
      if (document.visibilityState === "hidden") setOpen(false);
    };
    document.addEventListener("visibilitychange", onHidden);
    void (async () => {
      const Detector = await loadDetector();
      if (stopped) return;
      const detector = new Detector({ formats: FORMATS });
      const media = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      if (stopped) {
        media.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = media;
      const frame = videoRef.current;
      if (!frame) return;
      video = frame;
      frame.srcObject = media;
      await frame.play();
      if (stopped) return;
      setCamera("on");
      helpTimer = window.setTimeout(() => setHelp(true), HELP_AFTER_MS);
      timer = window.setInterval(() => {
        if (busy || stopped) return;
        busy = true;
        detector
          .detect(frame)
          .then((codes) => {
            const code = codes[0]?.rawValue;
            if (code && !stopped) {
              stopped = true;
              scanned.current = true;
              stream?.getTracks().forEach((track) => track.stop());
              onScan(code);
              setOpen(false);
            }
          })
          .catch(() => undefined)
          .finally(() => {
            busy = false;
          });
      }, 300);
    })()
      // Caméra refusée ou absente, moteur introuvable : il reste la douchette et le clavier.
      .catch(() => {
        if (!stopped) setCamera("off");
      });
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onHidden);
      window.clearInterval(timer);
      window.clearTimeout(helpTimer);
      stream?.getTracks().forEach((track) => track.stop());
      if (video) video.srcObject = null;
      setCamera("off");
      setHelp(false);
    };
  }, [open, onScan]);

  const openScanner = () => {
    scanned.current = false;
    // Sans caméra du tout, la fenêtre s'ouvre directement sur la saisie.
    if (typeof navigator.mediaDevices?.getUserMedia === "function") setCamera("preparing");
    setOpen(true);
  };

  const use = () => {
    const code = typed.trim();
    if (!code) return;
    scanned.current = true;
    onScan(code);
    setTyped("");
    setOpen(false);
  };

  return (
    <>
      {tile ? (
        <button
          type="button"
          onClick={openScanner}
          className={cn(
            className,
            "flex min-h-[120px] flex-[1_1_200px] flex-col items-center justify-center gap-2.5 rounded-[18px] border-2 border-dashed border-input bg-background text-[17px] font-bold text-encre-2",
            "outline-none hover:border-stock hover:text-stock-encre focus-visible:ring-3 focus-visible:ring-ring/50",
          )}
        >
          <ScanBarcode className="size-[30px]" aria-hidden />
          {label ?? t.scan}
        </button>
      ) : (
        <Button
          type="button"
          variant={variant}
          size="standard"
          className={className}
          onClick={openScanner}
        >
          <ScanBarcode aria-hidden />
          {label ?? t.scan}
        </Button>
      )}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="sm:max-w-md"
          onCloseAutoFocus={(event) => {
            if (scanned.current && !restoreFocus) event.preventDefault();
          }}
        >
          <DialogHeader>
            <DialogTitle>{t.scanTitle}</DialogTitle>
            {camera !== "off" && (
              <DialogDescription role="status">
                {camera === "preparing" ? t.scanPreparing : help ? t.scanHelp : t.scanCamera}
              </DialogDescription>
            )}
          </DialogHeader>
          <video
            ref={videoRef}
            muted
            playsInline
            aria-label={t.scanTitle}
            className={cn("w-full rounded-tuile bg-muted", camera !== "on" && "hidden")}
          />
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              use();
            }}
          >
            <label htmlFor={inputId} className="block text-libelle">
              {t.scanTyped}
            </label>
            <input
              id={inputId}
              autoFocus={camera === "off"}
              inputMode="numeric"
              autoComplete="off"
              value={typed}
              onChange={(event) => setTyped(event.target.value)}
              className={cn(fieldClasses("stock"), "min-h-bouton px-4 text-xl numeric")}
            />
            <DialogFooter>
              <Button type="submit" variant="stock" disabled={!typed.trim()}>
                {t.scanUse}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
