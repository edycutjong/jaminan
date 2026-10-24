import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, Rental } from "@/lib/api";
import { useRental } from "@/lib/useRental";

vi.mock("@/lib/api", async (orig) => ({ ...(await orig<typeof import("@/lib/api")>()), api: vi.fn() }));
import { api } from "@/lib/api";

const rental = (state: string) => ({ id: "R-1", state }) as Rental;
const mocked = vi.mocked(api);

beforeEach(() => mocked.mockReset());
afterEach(() => vi.useRealTimers());

describe("useRental", () => {
  it("fetches nothing until the key has been read from this phone", async () => {
    const { result } = renderHook(() => useRental("R-1", undefined));
    expect(await result.current.load()).toBeNull();
    expect(mocked).not.toHaveBeenCalled();
    expect(result.current.r).toBeNull();
  });

  it("loads the rental with this phone's key", async () => {
    mocked.mockResolvedValue(rental("OUT"));
    const { result } = renderHook(() => useRental("R-1", "k"));
    await waitFor(() => expect(result.current.r?.state).toBe("OUT"));
    expect(mocked).toHaveBeenCalledWith("/rentals/R-1", { key: "k" });
    expect(result.current.err).toBeNull();
  });

  it("shows an ApiError's message and a plain error's text", async () => {
    mocked.mockRejectedValueOnce(new ApiError(403, "FORBIDDEN", "needs the shop's key"));
    const { result } = renderHook(() => useRental("R-1", "k"));
    await waitFor(() => expect(result.current.err).toBe("needs the shop's key"));
    mocked.mockRejectedValueOnce(new Error("offline"));
    await act(async () => { await result.current.load(); });
    expect(result.current.err).toBe("Error: offline");
    expect(result.current.r).toBeNull();
  });

  it("drops a response that arrives after a newer request, whether it succeeds or fails", async () => {
    let slowOk!: (r: Rental) => void;
    let slowFail!: (e: unknown) => void;
    mocked.mockReset();
    mocked.mockImplementationOnce(() => new Promise<any>((res) => { slowOk = res; }));
    const { result } = renderHook(() => useRental("R-1", "k"));
    mocked.mockResolvedValueOnce(rental("RETURNED"));
    await act(async () => { await result.current.load(); });
    expect(result.current.r?.state).toBe("RETURNED");
    await act(async () => { slowOk(rental("OLD")); });
    expect(result.current.r?.state).toBe("RETURNED");

    mocked.mockImplementationOnce(() => new Promise<any>((_, rej) => { slowFail = rej; }));
    let first!: Promise<Rental | null>;
    act(() => { first = result.current.load(); });
    mocked.mockResolvedValueOnce(rental("SETTLED"));
    await act(async () => { await result.current.load(); });
    await act(async () => { slowFail(new Error("late")); await first; });
    expect(result.current.err).toBeNull();
    expect(result.current.r?.state).toBe("SETTLED");
  });

  it("polls every 3 s only while the rental is in a waiting state", async () => {
    vi.useFakeTimers();
    mocked.mockResolvedValue(rental("APPROVED"));
    const states = ["APPROVED"];
    const { result, unmount } = renderHook(() => useRental("R-1", "k", states));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.r?.state).toBe("APPROVED");
    const before = mocked.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(mocked.mock.calls.length).toBe(before + 1);
    mocked.mockResolvedValue(rental("OUT"));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    const after = mocked.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(9000); });
    expect(mocked.mock.calls.length).toBe(after);   // OUT is not in the waiting list: polling stops
    unmount();
  });

  it("clears a pending poll when the screen goes away", async () => {
    vi.useFakeTimers();
    mocked.mockResolvedValue(rental("APPROVED"));
    const { unmount } = renderHook(() => useRental("R-1", "k", ["APPROVED"]));
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    const n = mocked.mock.calls.length;
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(mocked.mock.calls.length).toBe(n);
  });

  it("lets a screen set the rental from an action's reply and clear the error", async () => {
    mocked.mockRejectedValueOnce(new Error("x"));
    const { result } = renderHook(() => useRental("R-1", "k"));
    await waitFor(() => expect(result.current.err).toBe("Error: x"));
    act(() => { result.current.setR(rental("HELD")); });
    expect(result.current.r?.state).toBe("HELD");
    expect(result.current.err).toBeNull();
  });
});
