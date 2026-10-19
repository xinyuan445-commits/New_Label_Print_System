import { api, ApiError } from "./api";
import { agentFetch, probeLocalAgent } from "./localAgent";
import { BROWSER_PRINTER, openBrowserPrint } from "./browserLabelPrint";

export type PrintResult = {
  printed: number;
  registered: number;
  run_id: string;
  output_dir?: string;
  printer: string;
};
type Prepared = {
  run_id: string;
  label_count: number;
  bundle_sha256: string;
  bundle_url: string;
  pdf_url?: string;
  receipt?: string;
};
type Pending = Prepared & { owner_id: number; browser_receipt?: ClientReceipt };
type ClientReceipt = {
  run_id: string;
  status: string;
  receipt: string;
  bundle_sha256: string;
  printer: string;
  printed: number;
  output_dir?: string;
};
const KEY = "label-print.pending-client-job.v1";
export const PRINT_EVENT = "label-print-job-changed";
let active = false;
export function isClientPrintActive() {
  return active;
}
export class ClientPrintError extends Error {}

export function pendingClientPrint(ownerId: number): Pending | null {
  const value = localStorage.getItem(KEY);
  if (!value) return null;
  const pending = JSON.parse(value) as Pending;
  return pending.owner_id === ownerId ? pending : null;
}
function setPending(value: Pending | null) {
  if (value) localStorage.setItem(KEY, JSON.stringify(value));
  else localStorage.removeItem(KEY);
  window.dispatchEvent(new Event(PRINT_EVENT));
}
async function finish(pending: Pending, receipt: ClientReceipt) {
  if (
    receipt.run_id !== pending.run_id ||
    receipt.bundle_sha256 !== pending.bundle_sha256 ||
    receipt.printed !== pending.label_count ||
    receipt.status !== "done"
  ) {
    throw new ClientPrintError("上次打印结果尚未确认，请先核对打印机");
  }
  const result = await api<PrintResult>(`/api/u8/print/${pending.run_id}/complete`, {
    method: "POST",
    body: JSON.stringify(receipt),
  });
  setPending(null);
  return result;
}
export async function recoverClientPrint(ownerId: number): Promise<PrintResult | null> {
  const pending = pendingClientPrint(ownerId);
  if (!pending) return null;
  let receipt: ClientReceipt;
  try {
    receipt =
      pending.browser_receipt ?? (await agentFetch<ClientReceipt>(`/label-jobs/${pending.run_id}`));
  } catch {
    throw new ClientPrintError("无法确认上次打印结果，请检查打印助手和打印机");
  }
  return finish(pending, receipt);
}
export function dismissClientPrint(ownerId: number) {
  if (pendingClientPrint(ownerId)) setPending(null);
}
export async function clientLabelPrint(
  path: string,
  body: unknown,
  ownerId: number,
): Promise<PrintResult> {
  if (pendingClientPrint(ownerId)) throw new ClientPrintError("请先处理上次打印任务");
  const browser = (body as { printer?: string })?.printer === BROWSER_PRINTER;
  if (!browser) {
    const agent = await probeLocalAgent();
    if (!agent?.capabilities?.includes("driver-labels-v1")) {
      throw new ClientPrintError("请安装或更新本机打印助手，或选择浏览器打印");
    }
  }
  const pending: Pending = {
    ...(await api<Prepared>(path, { method: "POST", body: JSON.stringify(body) })),
    owner_id: ownerId,
  };
  if (browser) {
    if (!pending.pdf_url || !pending.receipt) throw new ClientPrintError("打印内容不完整");
    if (!(await openBrowserPrint(pending.pdf_url, pending.label_count)))
      throw new ClientPrintError("已取消打印");
    const receipt: ClientReceipt = {
      run_id: pending.run_id,
      status: "done",
      receipt: pending.receipt,
      bundle_sha256: pending.bundle_sha256,
      printer: BROWSER_PRINTER,
      printed: pending.label_count,
    };
    active = true;
    try {
      setPending({ ...pending, browser_receipt: receipt });
      return await finish(pending, receipt);
    } finally {
      active = false;
      window.dispatchEvent(new Event(PRINT_EVENT));
    }
  }
  const response = await fetch(pending.bundle_url, { credentials: "include" });
  if (!response.ok)
    throw new ApiError(response.status, (await response.json()) as { error: string });
  const bundle = await response.arrayBuffer();
  // The client hashes the binary; its reply must match the server's prepared digest.
  // Persist before sending so lost replies never require another print submission.
  active = true;
  try {
    setPending(pending);
    let receipt: ClientReceipt;
    try {
      receipt = await agentFetch<ClientReceipt>(
        "/print-labels",
        {
          method: "POST",
          headers: { "Content-Type": "application/octet-stream" },
          body: bundle,
        },
        310_000,
      );
    } catch {
      const recovered = await recoverClientPrint(ownerId);
      if (!recovered) throw new ClientPrintError("打印结果尚未确认");
      return recovered;
    }
    return await finish(pending, receipt);
  } finally {
    active = false;
    window.dispatchEvent(new Event(PRINT_EVENT));
  }
}
