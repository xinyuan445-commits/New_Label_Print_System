import { useEffect, useState } from "react";
import {
  PRINT_EVENT,
  dismissClientPrint,
  pendingClientPrint,
  recoverClientPrint,
  isClientPrintActive,
} from "../lib/clientLabelPrint";
import { ApiError } from "../lib/api";
import { queryClient } from "../lib/queryClient";
import { Button } from "./ui/Button";

export function ClientPrintRecovery({ ownerId }: { ownerId: number }) {
  const [pending, setPending] = useState(() => pendingClientPrint(ownerId));
  const [busy, setBusy] = useState(false);
  const [printing, setPrinting] = useState(isClientPrintActive);
  const [error, setError] = useState("");
  useEffect(() => {
    const refresh = () => {
      setPending(pendingClientPrint(ownerId));
      setPrinting(isClientPrintActive());
    };
    refresh();
    window.addEventListener(PRINT_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(PRINT_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, [ownerId]);
  if (!pending) return null;
  async function recover() {
    setBusy(true);
    setError("");
    try {
      await recoverClientPrint(ownerId);
      void queryClient.invalidateQueries({ queryKey: ["u8", "pending-bills"] });
      void queryClient.invalidateQueries({ queryKey: ["history"] });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? "打印已提交，登记未完成，请重试确认"
          : cause instanceof Error
            ? cause.message
            : "确认失败",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      role="status"
      className="mx-6 mt-3 flex shrink-0 flex-wrap items-center gap-3 rounded-md border border-amber-700 bg-amber-950/30 px-4 py-3 text-sm"
    >
      <span>{printing ? "正在提交打印任务…" : "有一笔打印任务待确认"}</span>
      <Button variant="secondary" disabled={busy || printing} onClick={() => void recover()}>
        {busy ? "确认中…" : "确认打印结果"}
      </Button>
      <Button
        variant="ghost"
        disabled={busy || printing}
        onClick={() => {
          if (
            window.confirm(
              "请先核对是否已出纸。结束任务不会补印或登记；已打出的标签请保留流水号，避免重复使用。确定结束？",
            )
          )
            dismissClientPrint(ownerId);
        }}
      >
        核对后结束任务
      </Button>
      {error && <span className="text-rose-400">{error}</span>}
    </div>
  );
}
