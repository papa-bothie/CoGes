"use client";

import { ScanBarcode } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

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
import { labels } from "@/lib/labels";
import { cn } from "@/lib/utils";

/** L'API native `BarcodeDetector` (Chrome Android, Chrome et Edge) : absente des types DOM. */
type Detected = { rawValue: string };
type Detector = { detect: (source: HTMLVideoElement) => Promise<Detected[]> };
type DetectorConstructor = new (options: { formats: string[] }) => Detector;

function nativeDetector(): DetectorConstructor | null {
  if (typeof window === "undefined") return null;
  const candidate = (window as unknown as { BarcodeDetector?: DetectorConstructor })
    .BarcodeDetector;
  return candidate ?? null;
}

const FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128"];

/**
 * « Scanner le code-barres » (ADR 0066, choix du 2026-10-08) : la caméra par l'API native
 * du navigateur quand elle existe ; sinon — iPhone, Firefox, ordinateur sans caméra — le
 * champ reçoit ce que tape une douchette, ou le clavier. Facultatif : sans code, le serveur
 * en génère un.
 */
export function BarcodeScanButton({ onScan }: { onScan: (code: string) => void }) {
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [cameraOn, setCameraOn] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const inputId = useId();
  const t = labels.products.newForm;

  useEffect(() => {
    if (!open) return;
    const Detector = nativeDetector();
    if (!Detector || !navigator.mediaDevices?.getUserMedia) return;
    let stream: MediaStream | null = null;
    let timer: number | undefined;
    let stopped = false;
    const detector = new Detector({ formats: FORMATS });
    void navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "environment" } })
      .then(async (media) => {
        if (stopped) {
          media.getTracks().forEach((track) => track.stop());
          return;
        }
        stream = media;
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = media;
        await video.play();
        setCameraOn(true);
        timer = window.setInterval(() => {
          void detector.detect(video).then((codes) => {
            const code = codes[0]?.rawValue;
            if (code && !stopped) {
              onScan(code);
              setOpen(false);
            }
          });
        }, 300);
      })
      // Caméra refusée ou absente : il reste la douchette et le clavier.
      .catch(() => setCameraOn(false));
    return () => {
      stopped = true;
      window.clearInterval(timer);
      stream?.getTracks().forEach((track) => track.stop());
      setCameraOn(false);
    };
  }, [open, onScan]);

  const use = () => {
    const code = typed.trim();
    if (!code) return;
    onScan(code);
    setTyped("");
    setOpen(false);
  };

  return (
    <>
      <Button type="button" variant="secondaire" size="standard" onClick={() => setOpen(true)}>
        <ScanBarcode aria-hidden />
        {t.scan}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.scanTitle}</DialogTitle>
            {cameraOn && <DialogDescription>{t.scanCamera}</DialogDescription>}
          </DialogHeader>
          <video
            ref={videoRef}
            muted
            playsInline
            className={cn("w-full rounded-tuile bg-muted", !cameraOn && "hidden")}
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
              autoFocus={!cameraOn}
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
