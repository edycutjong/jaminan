import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ANGLE_NAMES, ApiError, CLASS_ID, PART_ID, adoptUrlKey, api, frameUrl, human, keyFor, saveKey, usd,
} from "@/lib/api";

beforeEach(() => localStorage.clear());
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

const reply = (status: number, body: string, statusText = "") => new Response(body, { status, statusText });
const stubFetch = (res: Response) => {
  const fn = vi.fn().mockImplementation(async () => res.clone());
  vi.stubGlobal("fetch", fn);
  return fn;
};

describe("keys", () => {
  it("round-trips a key per rental and role", () => {
    expect(keyFor("R-1", "shop")).toBeNull();
    saveKey("R-1", "shop", "abc");
    expect(keyFor("R-1", "shop")).toBe("abc");
    expect(keyFor("R-1", "renter")).toBeNull();
  });

  it("reads no key on the server, where there is no window", () => {
    vi.stubGlobal("window", undefined);
    expect(keyFor("R-1", "shop")).toBeNull();
  });

  it("adopts the renter key from the link and strips it from the address bar, keeping the rest", () => {
    window.history.replaceState(null, "", "/app/r/R-1?k=secret&x=1#top");
    adoptUrlKey("R-1");
    expect(keyFor("R-1", "renter")).toBe("secret");
    expect(window.location.pathname + window.location.search + window.location.hash).toBe("/app/r/R-1?x=1#top");
  });

  it("strips nothing and stores nothing when the link carries no key", () => {
    window.history.replaceState(null, "", "/app/r/R-2");
    adoptUrlKey("R-2");
    expect(keyFor("R-2", "renter")).toBeNull();
    expect(window.location.pathname + window.location.search).toBe("/app/r/R-2");
  });

  it("leaves a bare path when the key was the only parameter", () => {
    window.history.replaceState(null, "", "/app/r/R-3?k=only");
    adoptUrlKey("R-3");
    expect(window.location.pathname + window.location.search).toBe("/app/r/R-3");
  });
});

describe("api()", () => {
  it("GETs with the capability key header and never caches", async () => {
    const fn = stubFetch(reply(200, '{"id":"R-1"}'));
    expect(await api("/rentals/R-1", { key: "k1" })).toEqual({ id: "R-1" });
    const [url, init] = fn.mock.calls[0];
    expect(url).toBe("/api/rentals/R-1");
    expect(init).toMatchObject({ method: "GET", cache: "no-store", headers: { "X-Jaminan-Key": "k1" } });
    expect(init.body).toBeUndefined();
  });

  it("POSTs a JSON body with a content type, and sends no key header without a key", async () => {
    const fn = stubFetch(reply(200, "{}"));
    await api("/rentals", { body: { days: 2 } });
    const init = fn.mock.calls[0][1];
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"days":2}');
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("honours an explicit method and posts a form untouched", async () => {
    const fn = stubFetch(reply(200, "{}"));
    const form = new FormData();
    form.set("angle", "3");
    await api("/rentals/R-1/photos", { form });
    expect(fn.mock.calls[0][1].body).toBe(form);
    expect(fn.mock.calls[0][1].method).toBe("POST");
    await api("/rentals/R-1", { method: "DELETE", body: { a: 1 } });
    expect(fn.mock.calls[1][1].method).toBe("DELETE");
  });

  it("returns an empty object for an empty body", async () => {
    stubFetch(reply(200, ""));
    expect(await api("/x")).toEqual({});
  });

  it("turns an error body into an ApiError with the server's code and message", async () => {
    stubFetch(reply(409, '{"error":"BASELINE_LOCKED","message":"already confirmed"}'));
    const e = await api("/x").catch((x) => x);
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ status: 409, code: "BASELINE_LOCKED", message: "already confirmed" });
  });

  it("falls back to detail, then status text, and a generic code, when the error body is thin", async () => {
    stubFetch(reply(422, '{"detail":"bad field"}'));
    expect(await api("/x").catch((x) => x)).toMatchObject({ code: "HTTP_422", message: "bad field" });
    stubFetch(reply(503, "{}", "Service Unavailable"));
    expect(await api("/x").catch((x) => x)).toMatchObject({ code: "HTTP_503", message: "Service Unavailable" });
  });

  it("keeps the first 200 characters of a non-JSON error page", async () => {
    stubFetch(reply(502, "x".repeat(500), "Bad Gateway"));
    const e = await api("/x").catch((x) => x);
    expect(e).toMatchObject({ status: 502, code: "HTTP_502", message: "x".repeat(200) });
  });
});

describe("formatters", () => {
  it("formats cents as dollars and a dash for no amount", () => {
    expect(usd(1800)).toBe("$18.00");
    expect(usd(0)).toBe("$0.00");
    expect(usd(null)).toBe("—");
    expect(usd(undefined)).toBe("—");
  });

  it("turns snake_case into words", () => {
    expect(human("mirror_housing")).toBe("mirror housing");
  });

  it("builds frame URLs: none for a missing hash, whole frame, or a cropped region at a scale", () => {
    expect(frameUrl(null)).toBe("");
    expect(frameUrl(undefined)).toBe("");
    expect(frameUrl("abc")).toBe("/api/frames/abc");
    expect(frameUrl("abc", null)).toBe("/api/frames/abc");
    expect(frameUrl("abc", [0.4, 0.5, 0.1, 0.25])).toBe("/api/frames/abc?bbox=0.4000,0.5000,0.1000,0.2500&scale=1");
    expect(frameUrl("abc", [0.4, 0.5, 0.1, 0.25], 2)).toContain("&scale=2");
  });

  it("names all eight angles in both languages and the Indonesian part and damage words", () => {
    expect(Object.keys(ANGLE_NAMES)).toHaveLength(8);
    expect(ANGLE_NAMES[3]).toEqual({ en: "Left side", id: "Sisi kiri" });
    expect(PART_ID.mirror_housing).toBe("rumah spion");
    expect(CLASS_ID.crack).toBe("retak");
  });
});
