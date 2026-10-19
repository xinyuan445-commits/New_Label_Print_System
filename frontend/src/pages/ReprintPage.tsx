import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { PrintPageTabs } from "../components/PrintPageTabs";
import { Button } from "../components/ui/Button";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { Select } from "../components/ui/Select";
import { useLocalPrinters } from "../hooks/useLocalPrinters";
import { useMe } from "../hooks/useMe";
import { useTemplates } from "../hooks/useTemplates";
import { ApiError, api } from "../lib/api";
import { BROWSER_PRINTER } from "../lib/browserLabelPrint";
import { ClientPrintError, clientLabelPrint } from "../lib/clientLabelPrint";
import { readCsrfCookie } from "../lib/csrf";
import {
  defaultLocalPrinter,
  readLocalPrinterSettings,
  visibleLocalPrinters,
} from "../lib/localPrinterSettings";

type OriginalLabel = {
  sn: string;
  barcode: string;
  document_number: string;
  item_code: string;
  item_name: string;
  batch: string;
  quantity: string;
  unit: string;
  warehouse: string;
  location: string;
  specification: string;
  printed_at: string;
  printed_by: string;
  line_number: number | null;
  template_id: number | null;
};

function errorText(cause: unknown) {
  if (cause instanceof ClientPrintError) return cause.message;
  if (cause instanceof ApiError) {
    const messages: Record<string, string> = {
      label_not_found: "未找到该流水号的打印记录",
      ambiguous_label: "该流水号对应多条不同标签，请核对记录",
      invalid_label_record: "原打印记录不完整，无法补打",
      u8_not_configured: "尚未配置 U8 数据库连接",
      u8_query_failed: "打印记录查询失败，请检查数据库连接",
      u8_database_mismatch: "数据库账套与配置不一致",
      u8_read_only: "当前账套仅供查询",
      printer_not_found: "打印机不可用，请重新选择",
      printer_failed: "补打失败，请检查打印机",
      print_failed: "补打失败，请检查模板和打印机",
      template_not_found: "模板已不存在，请重新选择",
    };
    return messages[cause.code] ?? "操作失败，请核对输入后重试";
  }
  return "操作失败，请稍后重试";
}

export function ReprintPage() {
  const { data: me } = useMe();
  const templates = useTemplates();
  const printers = useLocalPrinters();
  const [settings, setSettings] = useState(readLocalPrinterSettings);
  const visiblePrinters = [...visibleLocalPrinters(printers.data ?? [], settings), BROWSER_PRINTER];
  const [sn, setSn] = useState("");
  const [label, setLabel] = useState<OriginalLabel | null>(null);
  const [templateId, setTemplateId] = useState("");
  const [printer, setPrinter] = useState("");
  const [copies, setCopies] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [completion, setCompletion] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [queryOnly, setQueryOnly] = useState(true);

  useEffect(() => {
    void api<{ query_only: boolean }>("/api/u8/bill-types")
      .then((result) => setQueryOnly(result.query_only))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const names = printers.data ?? [];
    const visible = visibleLocalPrinters(names, settings);
    setPrinter((value) =>
      visible.includes(value) || value === BROWSER_PRINTER
        ? value
        : defaultLocalPrinter(names, settings) || BROWSER_PRINTER,
    );
  }, [printers.data, settings]);

  useEffect(() => {
    const refresh = () => setSettings(readLocalPrinterSettings());
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, []);

  useEffect(() => {
    if (!templates.data || !templateId) return;
    if (!templates.data.some((item) => String(item.id) === templateId)) setTemplateId("");
  }, [templates.data, templateId]);

  useEffect(() => {
    if (completion === null) return;
    const timer = window.setTimeout(() => setCompletion(null), 3000);
    return () => window.clearTimeout(timer);
  }, [completion]);

  useEffect(() => {
    if (!previewUrl) return;
    const overflow = document.body.style.overflow;
    const focus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewUrl(null);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.cancelAnimationFrame(frame);
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", onKey);
      URL.revokeObjectURL(previewUrl);
      focus?.focus();
    };
  }, [previewUrl]);

  async function search() {
    if (busy) return;
    if (!sn.trim()) {
      setError("请输入流水号");
      return;
    }
    setBusy(true);
    setError("");
    setLabel(null);
    try {
      const params = new URLSearchParams({ sn: sn.trim() });
      const result = await api<{ label: OriginalLabel }>(`/api/u8/reprint?${params}`);
      setLabel(result.label);
      setCopies("1");
      let preferred = result.label.template_id ? String(result.label.template_id) : "";
      if (!preferred && me?.id !== undefined) {
        try {
          preferred =
            localStorage.getItem(`barcodelabelgen.default-bill-template.v1.${me.id}`) ?? "";
        } catch {
          /* no stored preference */
        }
      }
      setTemplateId(preferred);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  async function execute(preview: boolean) {
    if (!label || !templateId || busy) return;
    const count = Number(copies);
    if (!Number.isInteger(count) || count < 1 || count > 100) {
      setError("补打份数需为 1～100 的整数");
      return;
    }
    if (!preview && !printer) {
      setError("请选择打印机");
      return;
    }
    setBusy(true);
    setError("");
    const body = { sn: label.sn, template_id: Number(templateId), printer, copies: count };
    try {
      if (preview) {
        const headers = new Headers({ "Content-Type": "application/json" });
        const csrf = readCsrfCookie();
        if (csrf) headers.set("X-CSRF-Token", csrf);
        const response = await fetch("/api/u8/reprint/preview", {
          method: "POST",
          credentials: "include",
          headers,
          body: JSON.stringify(body),
        });
        if (!response.ok)
          throw new ApiError(response.status, (await response.json()) as { error: string });
        setPreviewUrl(URL.createObjectURL(await response.blob()));
      } else {
        const result = await clientLabelPrint("/api/u8/reprint", body, me!.id);
        setCompletion(
          result.output_dir
            ? `已保存 ${result.printed} 张补打标签到 ${result.output_dir}`
            : `已提交 ${result.printed} 张补打标签到 ${printer}`,
        );
      }
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  const fields = label
    ? [
        ["原单号", label.document_number],
        ["原行号", label.line_number?.toString() ?? ""],
        ["料号", label.item_code],
        ["名称", label.item_name],
        ["规格型号", label.specification],
        ["批号", label.batch],
        ["原标签数量", label.quantity],
        ["单位", label.unit],
        ["仓库", label.warehouse],
        ["货位", label.location],
        ["打印时间", label.printed_at.replace("T", " ").slice(0, 19)],
        ["打印人", label.printed_by],
      ]
    : [];

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold">标签补打</h1>
      <PrintPageTabs />
      {printers.isError && (
        <p className="text-sm text-amber-300">
          可直接使用浏览器打印 ·{" "}
          <a className="underline" href="/api/print-assistant/windows">
            下载安装
          </a>{" "}
          ·{" "}
          <a className="underline" href="http://127.0.0.1:9110/app/">
            本机入口
          </a>
        </p>
      )}
      <form
        className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <Input
          label="流水号（SN）"
          className="min-w-64 flex-1"
          value={sn}
          disabled={busy}
          maxLength={100}
          onChange={(event) => {
            setSn(event.target.value);
            setLabel(null);
            setError("");
          }}
        />
        <Button type="submit" disabled={busy || !sn.trim()}>
          {busy ? "处理中…" : "查询"}
        </Button>
      </form>
      {error && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}
      {label && (
        <>
          <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
            <h2 className="mb-5 text-lg font-semibold">原打印信息</h2>
            <dl className="grid gap-x-6 gap-y-5 sm:grid-cols-2 xl:grid-cols-4">
              {fields.map(([name, value]) => (
                <div key={name}>
                  <dt className="text-xs text-slate-400">{name}</dt>
                  <dd className="mt-1 break-words text-sm">{value || "—"}</dd>
                </div>
              ))}
            </dl>
            <div className="mt-5 border-t border-slate-800 pt-4">
              <p className="text-xs text-slate-400">原条码</p>
              <p className="mt-1 break-all font-mono text-sm">{label.barcode}</p>
            </div>
          </section>
          <section className="flex flex-wrap items-end gap-4 rounded-lg border border-slate-800 bg-slate-900/40 p-5">
            <Select
              label="模板"
              className="min-w-56"
              value={templateId}
              disabled={busy}
              onChange={(event) => setTemplateId(event.target.value)}
            >
              <option value="">选择模板</option>
              {(templates.data ?? []).map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.width_mm}×{item.height_mm} mm)
                  {item.id === label.template_id ? " · 原模板" : ""}
                </option>
              ))}
            </Select>
            <Select
              label="打印机"
              className="min-w-56 max-w-80"
              value={printer}
              disabled={busy || !visiblePrinters.length}
              onChange={(event) => setPrinter(event.target.value)}
            >
              {!visiblePrinters.length && (
                <option value="">{printers.isPending ? "读取中…" : "没有可选打印机"}</option>
              )}
              {visiblePrinters.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
            <Input
              label="补打份数"
              className="w-28"
              type="number"
              min="1"
              max="100"
              step="1"
              value={copies}
              disabled={busy}
              onChange={(event) => setCopies(event.target.value)}
            />
            <Button
              variant="secondary"
              disabled={busy || !templateId}
              onClick={() => void execute(true)}
            >
              预览标签
            </Button>
            <Button
              disabled={queryOnly || busy || !templateId || !printer}
              onClick={() => void execute(false)}
            >
              补打
            </Button>
          </section>
        </>
      )}
      <Modal
        open={completion !== null}
        onClose={() => setCompletion(null)}
        title="补打完成"
        footer={<Button onClick={() => setCompletion(null)}>确定</Button>}
      >
        <p className="break-all text-sm">{completion}</p>
      </Modal>
      {previewUrl &&
        createPortal(
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 p-2 sm:p-5">
            <section
              role="dialog"
              aria-modal="true"
              aria-label="标签预览"
              className="flex h-full w-full max-w-[1600px] flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl"
            >
              <header className="flex shrink-0 items-center justify-between border-b border-slate-800 px-5 py-3">
                <div>
                  <h2 className="text-lg font-semibold">标签预览</h2>
                  <p className="text-sm text-slate-400">
                    {label?.sn} · {copies} 张
                  </p>
                </div>
                <button
                  ref={closeRef}
                  type="button"
                  className="rounded-md border border-slate-700 px-4 py-2 text-sm"
                  onClick={() => setPreviewUrl(null)}
                >
                  关闭
                </button>
              </header>
              <div className="min-h-0 flex-1 bg-slate-100 p-3">
                <iframe
                  title="补打标签预览"
                  src={previewUrl}
                  className="h-full w-full rounded border border-slate-200 bg-white"
                />
              </div>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
