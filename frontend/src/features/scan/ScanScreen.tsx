import { useLingui } from "@lingui/react/macro";
import { useRouter } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState, type ChangeEvent } from "react";
import { Button } from "react-aria-components";
import { PRIMARY_BUTTON } from "../../shell/SignIn";
import { PANEL, SECONDARY_BUTTON } from "../ui";
import { createDecoder, type Decoder, type ScanHit } from "./decoder";
import { resolveScan } from "./resolvers";

/** The camera plumbing, replaceable in tests (jsdom has no camera and no image decoding). */
export interface ScanDeps {
  createDecoder: () => Promise<Decoder>;
  /** A bitmap of the current video frame or of a chosen photo; null while the video has no picture yet. */
  grabFrame: (source: HTMLVideoElement | Blob) => Promise<ImageBitmap | null>;
  /** Pause between two reads of the video. */
  intervalMs: number;
}

const defaultDeps: ScanDeps = {
  createDecoder: () => createDecoder(),
  grabFrame: async (source) => (source instanceof Blob ? createImageBitmap(source) : source.readyState < 2 ? null : createImageBitmap(source)),
  intervalMs: 150,
};

let deps: ScanDeps = defaultDeps;
/** Test seam: swaps the plumbing for one with fakes; `null` restores the real one. */
export const setScanDeps = (next: ScanDeps | null): void => {
  deps = next ?? defaultDeps;
};

type Phase =
  | { kind: "starting" }
  | { kind: "scanning" }
  | { kind: "insecure" }
  | { kind: "denied" }
  | { kind: "no-camera" }
  | { kind: "camera-failed" }
  | { kind: "reader-failed" }
  | { kind: "unknown"; hit: ScanHit };

const nameOf = (error: unknown): string => (error instanceof Error ? error.name : "");

function useCopy(text: string) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      /* clipboard blocked: the code stays selectable on screen */
    }
  };
  return { copied, copy };
}

function UnknownCode({ hit, onAgain }: { hit: ScanHit; onAgain: () => void }) {
  const { t } = useLingui();
  const { copied, copy } = useCopy(hit.text);
  return (
    <section aria-labelledby="unknown-heading" className={`${PANEL} flex flex-col gap-3`}>
      <h2 id="unknown-heading" className="text-section font-bold">
        {t`Unknown code`}
      </h2>
      <p className="text-ink-2">{t`This code is not one the hub knows. Its text:`}</p>
      <code className="max-h-40 overflow-y-auto rounded-r2 bg-sunken p-3 font-semibold break-all select-text">{hit.text}</code>
      <div className="flex flex-wrap gap-2">
        <Button onPress={() => void copy()} className={SECONDARY_BUTTON}>
          {copied ? t`Copied` : t`Copy`}
        </Button>
        <Button onPress={onAgain} className={PRIMARY_BUTTON}>
          {t`Scan again`}
        </Button>
      </div>
    </section>
  );
}

/** Four corner brackets: tells where to hold the code without hiding the picture. */
function Brackets() {
  const corner = "absolute size-10 border-accent";
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-[12%] max-sm:inset-[10%]">
      <span className={`${corner} top-0 left-0 rounded-tl-r3 border-t-4 border-l-4`} />
      <span className={`${corner} top-0 right-0 rounded-tr-r3 border-t-4 border-r-4`} />
      <span className={`${corner} bottom-0 left-0 rounded-bl-r3 border-b-4 border-l-4`} />
      <span className={`${corner} right-0 bottom-0 rounded-br-r3 border-r-4 border-b-4`} />
    </div>
  );
}

/**
 * The camera screen (spec 5.3/5.4): reads QR, Code 128 and Data Matrix, asks the registered
 * resolvers where the code leads, and goes straight there. Needs a secure context for the
 * camera; a photo of the code works everywhere.
 */
export function ScanScreen() {
  const { t } = useLingui();
  const router = useRouter();
  const secure = typeof window !== "undefined" && window.isSecureContext;
  const [phase, setPhase] = useState<Phase>(secure ? { kind: "starting" } : { kind: "insecure" });
  const [photoMiss, setPhotoMiss] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [round, setRound] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const decoder = useRef<Decoder | null>(null);
  const live = phase.kind === "scanning";

  // Opens the camera; leaving the screen (or a retry) stops it.
  useEffect(() => {
    if (!secure) return;
    let cancelled = false;
    let stream: MediaStream | null = null;
    const element = video.current;
    void (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error("no mediaDevices"), { name: "NotFoundError" });
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        if (element) {
          element.srcObject = stream;
          await element.play?.();
        }
        setPhase({ kind: "scanning" });
      } catch (error) {
        if (cancelled) return;
        const name = nameOf(error);
        if (name === "NotAllowedError" || name === "SecurityError") setPhase({ kind: "denied" });
        else if (name === "NotFoundError" || name === "OverconstrainedError") setPhase({ kind: "no-camera" });
        else setPhase({ kind: "camera-failed" });
      }
    })();
    return () => {
      cancelled = true;
      stream?.getTracks().forEach((track) => track.stop());
      if (element) element.srcObject = null;
    };
  }, [secure, attempt]);

  useEffect(() => () => decoder.current?.close(), []);

  const getDecoder = useCallback(async () => (decoder.current ??= await deps.createDecoder()), []);

  /** A hit either leads somewhere (navigate) or is shown as an unknown code. */
  const handle = useCallback(
    (hit: ScanHit): void => {
      const resolution = resolveScan(hit);
      navigator.vibrate?.(30);
      if (resolution) router.history.push(resolution.route);
      else setPhase({ kind: "unknown", hit });
    },
    [router],
  );

  // Reads the video while the camera is live, one frame at a time.
  useEffect(() => {
    if (!live) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const element = video.current;
        const frame = element ? await deps.grabFrame(element) : null;
        let hit: ScanHit | null = null;
        if (frame) {
          const reader = await getDecoder();
          try {
            hit = await reader.decode(frame);
          } finally {
            frame.close();
          }
        }
        if (stopped) return;
        if (hit) {
          handle(hit);
          return;
        }
      } catch {
        if (!stopped) setPhase({ kind: "reader-failed" });
        return;
      }
      timer = setTimeout(() => void tick(), deps.intervalMs);
    };
    void tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [live, round, getDecoder, handle]);

  const onPhoto = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setPhotoMiss(false);
    let hit: ScanHit | null = null;
    try {
      const frame = await deps.grabFrame(file);
      if (frame) {
        try {
          hit = await (await getDecoder()).decode(frame);
        } finally {
          frame.close();
        }
      }
    } catch {
      setPhase({ kind: "reader-failed" });
      return;
    }
    if (hit) handle(hit);
    else setPhotoMiss(true);
  };

  const retry = () => {
    setPhase({ kind: "starting" });
    setAttempt((n) => n + 1);
  };

  const again = () => {
    setPhotoMiss(false);
    setPhase({ kind: "scanning" });
    setRound((n) => n + 1);
  };

  const showVideo = phase.kind === "starting" || phase.kind === "scanning" || phase.kind === "unknown";

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
      <h1 className="text-title font-bold">{t`Scan`}</h1>

      {showVideo && (
        <div className="relative aspect-[3/4] w-full overflow-hidden rounded-r3 bg-[#0b0b0b] sm:aspect-[4/3]">
          <video ref={video} playsInline muted aria-label={t`Camera view`} className="size-full object-cover" />
          {phase.kind === "scanning" && <Brackets />}
          {phase.kind === "starting" && (
            <p role="status" className="absolute inset-0 grid place-items-center text-[#f5f5f5]">
              {t`Starting the camera…`}
            </p>
          )}
        </div>
      )}

      {phase.kind === "scanning" && (
        <p role="status" className="text-ink-2">
          {t`Hold a label's code inside the corners. QR, Code 128 and Data Matrix are read.`}
        </p>
      )}

      {phase.kind === "insecure" && (
        <section aria-labelledby="insecure-heading" className={`${PANEL} flex flex-col gap-2`}>
          <h2 id="insecure-heading" className="text-section font-bold">
            {t`The camera is not available here`}
          </h2>
          <p>{t`The camera needs a secure connection (HTTPS) or localhost. Open the hub through its HTTPS address, or choose a photo of the code below.`}</p>
        </section>
      )}

      {phase.kind === "denied" && (
        <section aria-labelledby="denied-heading" className={`${PANEL} flex flex-col gap-3`}>
          <h2 id="denied-heading" className="text-section font-bold">
            {t`The camera is blocked`}
          </h2>
          <p>{t`This browser blocked the camera for this site. Allow it in the site settings (the icon next to the address, then Camera), then try again.`}</p>
          <div>
            <Button onPress={retry} className={PRIMARY_BUTTON}>
              {t`Try again`}
            </Button>
          </div>
        </section>
      )}

      {phase.kind === "no-camera" && (
        <section aria-labelledby="none-heading" className={`${PANEL} flex flex-col gap-2`}>
          <h2 id="none-heading" className="text-section font-bold">
            {t`No camera`}
          </h2>
          <p>{t`No camera was found on this device. Choose a photo of the code instead.`}</p>
        </section>
      )}

      {phase.kind === "camera-failed" && (
        <section aria-labelledby="failed-heading" className={`${PANEL} flex flex-col gap-3`}>
          <h2 id="failed-heading" className="text-section font-bold">
            {t`The camera did not start`}
          </h2>
          <p>{t`Another app may be using the camera. Close it and try again.`}</p>
          <div>
            <Button onPress={retry} className={PRIMARY_BUTTON}>
              {t`Try again`}
            </Button>
          </div>
        </section>
      )}

      {phase.kind === "reader-failed" && (
        <section aria-labelledby="reader-heading" role="alert" className={`${PANEL} flex flex-col gap-3`}>
          <h2 id="reader-heading" className="text-section font-bold">
            {t`The code reader did not start`}
          </h2>
          <p>{t`Reload the page and try again. If it keeps failing, the browser may block WebAssembly.`}</p>
        </section>
      )}

      {phase.kind === "unknown" && <UnknownCode key={phase.hit.text} hit={phase.hit} onAgain={again} />}

      {photoMiss && <p role="alert">{t`No code found in this photo. Hold the camera closer and try again.`}</p>}

      <label className={`${SECONDARY_BUTTON} relative cursor-pointer self-start focus-within:outline-3 focus-within:outline-offset-2 focus-within:outline-link`}>
        {t`Choose a photo of a code`}
        <input
          type="file"
          accept="image/*"
          capture="environment"
          onChange={(event) => void onPhoto(event)}
          className="absolute inset-0 cursor-pointer opacity-0"
        />
      </label>
    </div>
  );
}
