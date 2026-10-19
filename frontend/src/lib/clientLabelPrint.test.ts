import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { agentFetch, probeLocalAgent } from "./localAgent";
import { clientLabelPrint, pendingClientPrint, recoverClientPrint } from "./clientLabelPrint";
import { BROWSER_PRINTER, openBrowserPrint } from "./browserLabelPrint";

vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: vi.fn(),
}));
vi.mock("./localAgent", () => ({ agentFetch: vi.fn(), probeLocalAgent: vi.fn() }));
vi.mock("./browserLabelPrint", () => ({
  BROWSER_PRINTER: "浏览器打印",
  openBrowserPrint: vi.fn(),
}));
const prepared = { run_id: "abc", label_count: 1, bundle_sha256: "hash", bundle_url: "/bundle" };
const receipt = {
  run_id: "abc",
  printed: 1,
  printer: "PDF",
  receipt: "secret",
  bundle_sha256: "hash",
  status: "done",
};
beforeEach(() => {
  vi.resetAllMocks();
  const values = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
    removeItem: (key: string) => values.delete(key),
  });
  vi.stubGlobal("window", { dispatchEvent: vi.fn() });
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, arrayBuffer: async () => new ArrayBuffer(1) }),
  );
  vi.mocked(probeLocalAgent).mockResolvedValue({
    agent: "test",
    version: "1",
    printers: [],
    last_poll_ok: false,
    capabilities: ["driver-labels-v1"],
  });
  vi.mocked(api)
    .mockResolvedValueOnce(prepared)
    .mockResolvedValue({ ...receipt, registered: 1 });
});
it("confirms lost replies by status without another submission", async () => {
  vi.mocked(agentFetch)
    .mockRejectedValueOnce(new Error("lost reply"))
    .mockResolvedValueOnce(receipt);
  expect((await clientLabelPrint("/print", {}, 1)).printed).toBe(1);
  expect(agentFetch).toHaveBeenNthCalledWith(2, "/label-jobs/abc");
  expect(
    vi.mocked(agentFetch).mock.calls.filter(([path]) => path === "/print-labels"),
  ).toHaveLength(1);
  expect(pendingClientPrint(1)).toBeNull();
});
it("keeps unknown jobs and blocks a fresh print until resolved", async () => {
  vi.mocked(agentFetch)
    .mockRejectedValueOnce(new Error("timeout"))
    .mockResolvedValueOnce({ ...receipt, status: "processing", printed: 0 });
  await expect(clientLabelPrint("/print", {}, 1)).rejects.toThrow("尚未确认");
  await expect(clientLabelPrint("/print", {}, 1)).rejects.toThrow("处理上次");
  expect(api).toHaveBeenCalledTimes(1);
  vi.mocked(agentFetch).mockResolvedValueOnce(receipt);
  expect((await recoverClientPrint(1))?.registered).toBe(1);
  expect(pendingClientPrint(1)).toBeNull();
});
it("browser printing needs no agent and cancellation never registers", async () => {
  vi.mocked(api)
    .mockReset()
    .mockResolvedValue({ ...prepared, receipt: "secret", pdf_url: "/print.pdf" });
  vi.mocked(openBrowserPrint).mockResolvedValue(false);
  await expect(clientLabelPrint("/print", { printer: BROWSER_PRINTER }, 1)).rejects.toThrow(
    "已取消",
  );
  expect(probeLocalAgent).not.toHaveBeenCalled();
  expect(agentFetch).not.toHaveBeenCalled();
  expect(api).toHaveBeenCalledTimes(1);
  expect(pendingClientPrint(1)).toBeNull();
});

it("browser mode registers only after the user's print confirmation", async () => {
  vi.mocked(api)
    .mockReset()
    .mockResolvedValueOnce({ ...prepared, receipt: "secret", pdf_url: "/print.pdf" })
    .mockResolvedValue({ ...receipt, registered: 1 });
  vi.mocked(openBrowserPrint).mockResolvedValue(true);
  await clientLabelPrint("/print", { printer: BROWSER_PRINTER }, 1);
  expect(probeLocalAgent).not.toHaveBeenCalled();
  expect(agentFetch).not.toHaveBeenCalled();
  expect(api).toHaveBeenLastCalledWith("/api/u8/print/abc/complete", expect.anything());
});

it("retries registration with the original receipt and no new print", async () => {
  vi.mocked(agentFetch).mockResolvedValue(receipt);
  vi.mocked(api)
    .mockReset()
    .mockResolvedValueOnce(prepared)
    .mockRejectedValueOnce(new Error("registration failed"));
  await expect(clientLabelPrint("/print", {}, 1)).rejects.toThrow("registration failed");
  expect(pendingClientPrint(1)?.run_id).toBe("abc");
  vi.mocked(api).mockResolvedValue({ ...receipt, registered: 1 });
  await recoverClientPrint(1);
  expect(
    vi.mocked(agentFetch).mock.calls.filter(([path]) => path === "/print-labels"),
  ).toHaveLength(1);
  expect(api).toHaveBeenLastCalledWith("/api/u8/print/abc/complete", expect.anything());
});
