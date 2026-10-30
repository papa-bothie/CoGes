import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/errors";

import {
  EnrollStep,
  MFA_MESSAGES,
  RecoveryCodesPanel,
  VerifyStep,
  cleanCode,
  groupedKey,
  mfaFailure,
} from "./mfa-steps";

type Call = { url: string; body: Record<string, unknown> };

let calls: Call[] = [];
let replies: Array<{ status: number; body: unknown }> = [];

function reply(status: number, body: unknown) {
  replies.push({ status, body });
}

beforeEach(() => {
  calls = [];
  replies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init.body ?? "{}")) });
      const next = replies.shift() ?? { status: 500, body: null };
      return new Response(JSON.stringify(next.body), {
        status: next.status,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

const TOKENS = { access_token: "jeton", token_type: "bearer", expires_in: 900 };
const error = (code: string, message = "…") => ({ error: { code, message, details: {} } });

describe("messages de la double authentification", () => {
  it("un code faux et un jeton échu ont chacun leur phrase", () => {
    expect(mfaFailure(new ApiError(401, "mfa_code_invalid", "…"))).toEqual({
      message: MFA_MESSAGES.wrongCode,
      expired: false,
    });
    expect(mfaFailure(new ApiError(401, "mfa_code_invalid", "…"), true).message).toBe(
      MFA_MESSAGES.wrongRecovery,
    );
    expect(mfaFailure(new ApiError(401, "mfa_challenge_invalid", "…"))).toEqual({
      message: MFA_MESSAGES.expired,
      expired: true,
    });
  });

  it("le freinage par compte rend la phrase du serveur, la même que pour le mot de passe", () => {
    const throttled = new ApiError(429, "rate_limited", "Trop d'essais. Réessayez dans 1 minute.", {
      scope: "account",
    });
    expect(mfaFailure(throttled).message).toBe("Trop d'essais. Réessayez dans 1 minute.");
  });

  it("ne garde que six chiffres et groupe la clé par quatre", () => {
    expect(cleanCode("12 3a45-67")).toBe("123456");
    expect(groupedKey("JBSWY3DPEHPK3PXP")).toBe("JBSW Y3DP EHPK 3PXP");
  });
});

describe("seconde étape de la connexion", () => {
  it("envoie le code saisi avec le jeton intermédiaire", async () => {
    reply(200, TOKENS);
    const done = vi.fn();
    render(<VerifyStep challenge="intermediaire" onDone={done} onRestart={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Code à 6 chiffres"), "123 456");
    await userEvent.click(screen.getByRole("button", { name: "Valider" }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(calls[0]).toEqual({
      url: "/api/v1/platform/auth/mfa/verify",
      body: { challenge_token: "intermediaire", code: "123456" },
    });
  });

  it("refuse un code incomplet sans appeler le serveur", async () => {
    render(<VerifyStep challenge="x" onDone={vi.fn()} onRestart={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Code à 6 chiffres"), "123");
    await userEvent.click(screen.getByRole("button", { name: "Valider" }));
    expect(screen.getByRole("alert")).toHaveTextContent(MFA_MESSAGES.codeRequired);
    expect(calls).toEqual([]);
  });

  it("passe au code de secours et le dit quand il ne sert plus", async () => {
    reply(401, error("mfa_code_invalid"));
    render(<VerifyStep challenge="x" onDone={vi.fn()} onRestart={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Utiliser un code de secours" }));
    await userEvent.type(screen.getByLabelText("Code de secours"), "abcd-efgh");
    await userEvent.click(screen.getByRole("button", { name: "Valider" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(MFA_MESSAGES.wrongRecovery);
    expect(calls[0]?.body).toEqual({ challenge_token: "x", recovery_code: "ABCD-EFGH" });
  });

  it("un jeton échu ramène au mot de passe", async () => {
    reply(401, error("mfa_challenge_invalid"));
    const restart = vi.fn();
    render(<VerifyStep challenge="x" onDone={vi.fn()} onRestart={restart} />);
    await userEvent.type(screen.getByLabelText("Code à 6 chiffres"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Valider" }));
    await userEvent.click(await screen.findByRole("button", { name: "Reprendre la connexion" }));
    expect(restart).toHaveBeenCalled();
  });
});

describe("enrôlement", () => {
  const ENROLLMENT = {
    secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
    otpauth_uri: "otpauth://totp/x",
    qr_svg: "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    account: "awa@exemple.com",
    issuer: "CoGes Administration",
  };

  it("demande le secret une seule fois, montre QR code et clé, puis rend les codes", async () => {
    reply(200, ENROLLMENT);
    reply(200, { ...TOKENS, recovery_codes: ["ABCD-EFGH"] });
    const activated = vi.fn();
    render(<EnrollStep challenge="inscription" onActivated={activated} onRestart={vi.fn()} />);
    expect(await screen.findByRole("img", { name: /QR code à scanner/ })).toBeInTheDocument();
    expect(screen.getByText("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Code à 6 chiffres"), "654321");
    await userEvent.click(
      screen.getByRole("button", { name: "Activer la double authentification" }),
    );
    await waitFor(() => expect(activated).toHaveBeenCalledWith(["ABCD-EFGH"]));
    expect(calls.map((call) => call.url)).toEqual([
      "/api/v1/platform/auth/mfa/enrollment",
      "/api/v1/platform/auth/mfa/enrollment/confirm",
    ]);
    expect(calls[1]?.body).toEqual({ challenge_token: "inscription", code: "654321" });
  });

  it("un premier code faux laisse réessayer", async () => {
    reply(200, ENROLLMENT);
    reply(401, error("mfa_code_invalid"));
    render(<EnrollStep challenge="x" onActivated={vi.fn()} onRestart={vi.fn()} />);
    await screen.findByRole("img", { name: /QR code/ });
    await userEvent.type(screen.getByLabelText("Code à 6 chiffres"), "000000");
    await userEvent.click(
      screen.getByRole("button", { name: "Activer la double authentification" }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(MFA_MESSAGES.wrongCode);
    expect(screen.getByLabelText("Code à 6 chiffres")).toBeInTheDocument();
  });
});

describe("codes de secours", () => {
  it("ne laisse continuer qu'après avoir dit qu'ils sont rangés", async () => {
    const next = vi.fn();
    render(<RecoveryCodesPanel codes={["ABCD-EFGH", "JKMN-PQRS"]} onContinue={next} />);
    expect(screen.getByRole("list", { name: "Codes de secours" })).toHaveTextContent("JKMN-PQRS");
    const go = screen.getByRole("button", { name: "Continuer vers l'administration" });
    expect(go).toBeDisabled();
    await userEvent.click(screen.getByLabelText("J'ai rangé ces codes en lieu sûr."));
    await userEvent.click(go);
    expect(next).toHaveBeenCalled();
  });
});
