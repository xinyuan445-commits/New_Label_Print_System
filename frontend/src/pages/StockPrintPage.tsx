import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "../components/ui/Button";
import { PrintPageTabs } from "../components/PrintPageTabs";
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

type Stock = {
  source: "current" | "position";
  stock_id: number;
  warehouse_code: string;
  warehouse_name: string;
  location_code: string;
  location_name: string;
  item_code: string;
  item_name: string;
  specification: string;
  unit: string;
  quantity: string;
  batch: string;
};

const keyOf = (row: Stock) => `${row.source}:${row.stock_id}`;
const templateKey = (userId: number) => `barcodelabelgen.default-stock-template.v1.${userId}`;

type SelectionReview = {
  keys: string[];
  selected: string[];
  quantities: Record<string, string>;
  packaging: Record<string, string>;
};

function currentHour() {
  const now = new Date();
  return `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, "0")}${String(now.getDate()).padStart(2, "0")}${String(now.getHours()).padStart(2, "0")}`;
}

function errorText(cause: unknown): string {
  if (cause instanceof ClientPrintError) return cause.message;
  if (cause instanceof ApiError) {
    const messages: Record<string, string> = {
      u8_not_configured: "尚未配置 U8 数据库连接",
      u8_database_mismatch: "数据库账套与配置不一致",
      u8_read_only: "当前账套仅供查询",
      u8_query_failed: "库存查询失败，请检查数据库连接",
      stock_changed: "库存已变化，请重新查询",
      invalid_quantity: "打印数量或包装方式无效",
      too_many_labels: "一次最多打印 1000 张标签",
      no_labels_for_line: "有存货未生成标签，请检查尾数设置",
      printer_not_found: "打印机不可用，请重新选择",
      printer_failed: "打印失败，请检查打印机",
      print_failed: "打印失败，请检查模板和打印机",
      trace_registration_failed: "打印已完成，但记录登记失败",
      file_exists: "同名标签文件已存在，请核对后重试",
    };
    return messages[cause.code] ?? "操作失败，请稍后重试";
  }
  return "操作失败，请稍后重试";
}

export function StockPrintPage() {
  const { data: me } = useMe();
  const templates = useTemplates();
  const printers = useLocalPrinters();
  const [printerSettings, setPrinterSettings] = useState(readLocalPrinterSettings);
  const visiblePrinters = [
    ...visibleLocalPrinters(printers.data ?? [], printerSettings),
    BROWSER_PRINTER,
  ];
  const [printer, setPrinter] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [defaultTemplateId, setDefaultTemplateId] = useState("");
  const [filters, setFilters] = useState({ warehouse: "", location: "", item: "", batch: "" });
  const [stock, setStock] = useState<Stock[]>([]);
  const [searched, setSearched] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [review, setReview] = useState<SelectionReview | null>(null);
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [packaging, setPackaging] = useState<Record<string, string>>({});
  const [includeRemainder, setIncludeRemainder] = useState(true);
  const [batchOpen, setBatchOpen] = useState(false);
  const [batchValue, setBatchValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [completion, setCompletion] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewCount, setPreviewCount] = useState(0);
  const [registrationRunId, setRegistrationRunId] = useState<string | null>(null);
  const [barcodeAccountCode, setBarcodeAccountCode] = useState("008");
  const [queryOnly, setQueryOnly] = useState(true);

  useEffect(() => {
    void api<{ barcode_account_code: string; query_only: boolean }>("/api/u8/bill-types")
      .then((result) => {
        setBarcodeAccountCode(result.barcode_account_code);
        setQueryOnly(result.query_only);
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (me?.id === undefined) return;
    const saved = localStorage.getItem(templateKey(me.id)) ?? "";
    setTemplateId(saved);
    setDefaultTemplateId(saved);
  }, [me?.id]);

  useEffect(() => {
    if (!templates.data || !defaultTemplateId || me?.id === undefined) return;
    if (templates.data.some((item) => String(item.id) === defaultTemplateId)) return;
    localStorage.removeItem(templateKey(me.id));
    setDefaultTemplateId("");
    setTemplateId("");
  }, [templates.data, defaultTemplateId, me?.id]);

  useEffect(() => {
    const names = printers.data ?? [];
    const visible = visibleLocalPrinters(names, printerSettings);
    setPrinter((current) =>
      visible.includes(current) || current === BROWSER_PRINTER
        ? current
        : defaultLocalPrinter(names, printerSettings) || BROWSER_PRINTER,
    );
  }, [printers.data, printerSettings]);

  useEffect(() => {
    const refresh = () => setPrinterSettings(readLocalPrinterSettings());
    window.addEventListener("storage", refresh);
    return () => window.removeEventListener("storage", refresh);
  }, []);

  useEffect(() => {
    if (completion === null) return;
    const timer = window.setTimeout(() => setCompletion(null), 3000);
    return () => window.clearTimeout(timer);
  }, [completion]);

  useEffect(() => {
    if (!previewUrl) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewUrl(null);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", onKey);
      URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const effective = stock.filter((row) => selected.includes(keyOf(row)));

  async function search() {
    setBusy(true);
    setError("");
    setNotice("");
    setSelected([]);
    setReview(null);
    setStock([]);
    setSearched(true);
    try {
      const params = new URLSearchParams(filters);
      const result = await api<{ stock: Stock[]; truncated: boolean }>(`/api/u8/stock?${params}`);
      setStock(result.stock);
      setQuantities(
        Object.fromEntries(
          result.stock.map((row) => [keyOf(row), Number(row.quantity).toFixed(2)]),
        ),
      );
      setPackaging({});
      if (result.truncated) setNotice("仅显示前 300 条，请缩小查询范围");
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  function lines() {
    return effective.map((row) => ({
      source: row.source,
      stock_id: row.stock_id,
      item_code: row.item_code,
      batch: row.batch,
      quantity: Number(quantities[keyOf(row)]),
      packaging: Number(packaging[keyOf(row)]),
    }));
  }

  function validate() {
    const entries = lines();
    if (!entries.length) {
      setError("请选择需要打印的存货");
      return null;
    }
    for (const entry of entries) {
      const available = Number(
        stock.find((row) => row.source === entry.source && row.stock_id === entry.stock_id)
          ?.quantity,
      );
      if (
        !Number.isFinite(entry.quantity) ||
        entry.quantity <= 0 ||
        entry.quantity > available ||
        !Number.isFinite(entry.packaging) ||
        entry.packaging <= 0
      ) {
        setError("打印数量不能超过库存，包装方式需大于 0");
        return null;
      }
    }
    return entries;
  }

  function count() {
    return lines().reduce((total, row) => {
      if (
        !Number.isFinite(row.quantity) ||
        !Number.isFinite(row.packaging) ||
        row.quantity <= 0 ||
        row.packaging <= 0
      )
        return total;
      const full = Math.floor(row.quantity / row.packaging);
      return (
        total + full + (includeRemainder && row.quantity - full * row.packaging > 0.001 ? 1 : 0)
      );
    }, 0);
  }

  function setDefaultTemplate() {
    if (me?.id === undefined || !templateId) return;
    const next = templateId === defaultTemplateId ? "" : templateId;
    if (next) localStorage.setItem(templateKey(me.id), next);
    else localStorage.removeItem(templateKey(me.id));
    setDefaultTemplateId(next);
  }

  async function preview() {
    if (!templateId) return;
    const entries = validate();
    if (!entries) return;
    const rows: Record<string, string>[] = [];
    const documentNumber = currentHour();
    for (const [index, entry] of entries.entries()) {
      const source = effective[index];
      const full = Math.floor(entry.quantity / entry.packaging);
      const remainder = entry.quantity - full * entry.packaging;
      const amounts = Array.from({ length: Math.min(full, 1001) }, () => entry.packaging);
      if (includeRemainder && remainder > 0.001) amounts.push(remainder);
      if (rows.length + amounts.length > 1000) {
        setError("一次最多预览 1000 张标签");
        return;
      }
      for (const amount of amounts) {
        const sn = `PREVIEW-${rows.length + 1}`;
        const quantity = amount.toFixed(2);
        rows.push({
          账套名: "科米龙",
          单据编码: documentNumber,
          行号: String(index + 1),
          物料编码: source.item_code,
          物料名称: source.item_name,
          批号: source.batch,
          数量: quantity,
          单位: source.unit,
          sn,
          仓库编码: source.warehouse_code,
          仓库名称: source.warehouse_name,
          货位编码: source.location_code,
          货位名称: source.location_name,
          规格型号: source.specification,
          条码: `${barcodeAccountCode}|${source.item_code}|${source.batch}|${quantity}|${sn}`,
        });
      }
    }
    if (!rows.length) {
      setError("没有可预览的标签");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const headers = new Headers({ "Content-Type": "application/json" });
      const csrf = readCsrfCookie();
      if (csrf) headers.set("X-CSRF-Token", csrf);
      const response = await fetch(`/api/templates/${templateId}/preview-variables`, {
        method: "POST",
        credentials: "include",
        headers,
        body: JSON.stringify({ rows }),
      });
      if (!response.ok) throw new Error(String(response.status));
      setPreviewCount(rows.length);
      setPreviewUrl(URL.createObjectURL(await response.blob()));
    } catch {
      setError("标签预览失败");
    } finally {
      setBusy(false);
    }
  }

  async function print() {
    if (!templateId || !printer) return;
    const entries = validate();
    if (!entries) return;
    setBusy(true);
    setError("");
    setRegistrationRunId(null);
    try {
      const result = await clientLabelPrint(
        "/api/u8/stock/print",
        {
          template_id: Number(templateId),
          printer,
          lines: entries,
          include_remainder: includeRemainder,
        },
        me!.id,
      );
      setCompletion(
        result.output_dir
          ? `已保存 ${result.printed} 张标签到 ${result.output_dir}`
          : `已提交 ${result.printed} 张标签到 ${printer}`,
      );
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  async function retryRegistration() {
    if (!registrationRunId) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<{ registered: number }>(
        `/api/u8/print/${registrationRunId}/register`,
        { method: "POST" },
      );
      setRegistrationRunId(null);
      setCompletion(`已登记 ${result.registered} 张标签`);
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setBusy(false);
    }
  }

  function renderStockTable(rows: Stock[], reviewMode = false) {
    const checked = reviewMode && review ? review.selected : selected;
    const quantityValues = reviewMode && review ? review.quantities : quantities;
    const packagingValues = reviewMode && review ? review.packaging : packaging;
    function changeSelection(keys: string[], enabled: boolean) {
      const next = (old: string[]) =>
        enabled ? [...new Set([...old, ...keys])] : old.filter((key) => !keys.includes(key));
      if (reviewMode) setReview((old) => (old ? { ...old, selected: next(old.selected) } : old));
      else {
        setSelected(next);
        setError("");
      }
    }
    function changeValue(field: "quantities" | "packaging", key: string, value: string) {
      if (reviewMode)
        setReview((old) => (old ? { ...old, [field]: { ...old[field], [key]: value } } : old));
      else {
        const setter = field === "quantities" ? setQuantities : setPackaging;
        setter((old) => ({ ...old, [key]: value }));
        setError("");
      }
    }
    return (
      <table className="w-full min-w-[1180px] text-left text-sm">
        <thead className="sticky top-0 bg-slate-900 text-slate-400">
          <tr>
            <th className="p-2">
              <label className="flex items-center gap-2 whitespace-nowrap">
                <input
                  type="checkbox"
                  aria-label={reviewMode ? "全选核对存货" : "全选存货"}
                  checked={rows.length > 0 && rows.every((row) => checked.includes(keyOf(row)))}
                  onChange={(event) => changeSelection(rows.map(keyOf), event.target.checked)}
                />
                选择
              </label>
            </th>
            <th className="p-2">仓库</th>
            <th className="p-2">货位</th>
            <th className="p-2">料号</th>
            <th className="p-2">名称</th>
            <th className="p-2">规格型号</th>
            <th className="p-2">批号</th>
            <th className="p-2 text-right">库存数量</th>
            <th className="p-2 text-right">打印数量</th>
            <th className="p-2">单位</th>
            <th className="p-2">包装方式</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = keyOf(row);
            return (
              <tr key={key} className="border-t border-slate-800">
                <td className="p-2">
                  <input
                    type="checkbox"
                    aria-label={`选择 ${row.item_code}`}
                    checked={checked.includes(key)}
                    onChange={(event) => changeSelection([key], event.target.checked)}
                  />
                </td>
                <td className="p-2">{row.warehouse_name}</td>
                <td className="p-2">{row.location_name || "—"}</td>
                <td className="p-2">{row.item_code}</td>
                <td className="p-2">{row.item_name}</td>
                <td className="p-2">{row.specification}</td>
                <td className="p-2">{row.batch || "—"}</td>
                <td className="p-2 text-right">{row.quantity}</td>
                <td className="p-2">
                  <input
                    className="w-28 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-right"
                    aria-label={`${row.item_code} 打印数量`}
                    type="number"
                    min="0"
                    max={row.quantity}
                    step="any"
                    value={quantityValues[key] ?? ""}
                    onChange={(event) => changeValue("quantities", key, event.target.value)}
                  />
                </td>
                <td className="p-2">{row.unit}</td>
                <td className="p-2">
                  <input
                    className="w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1"
                    aria-label={`${row.item_code} 包装方式`}
                    type="number"
                    min="0"
                    step="any"
                    value={packagingValues[key] ?? ""}
                    onChange={(event) => changeValue("packaging", key, event.target.value)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  }

  return (
    <div className="flex flex-col gap-3 md:h-full md:min-h-0">
      <header className="shrink-0">
        <h1 className="text-2xl font-bold">存货打印</h1>
      </header>
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
      <section className="shrink-0 rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <div className="grid gap-3 md:grid-cols-[repeat(4,minmax(0,1fr))_auto] md:items-end">
          <Input
            label="仓库"
            value={filters.warehouse}
            onChange={(event) => setFilters({ ...filters, warehouse: event.target.value })}
          />
          <Input
            label="货位"
            value={filters.location}
            onChange={(event) => setFilters({ ...filters, location: event.target.value })}
          />
          <Input
            label="料号 / 名称"
            value={filters.item}
            onChange={(event) => setFilters({ ...filters, item: event.target.value })}
          />
          <Input
            label="批号"
            value={filters.batch}
            onChange={(event) => setFilters({ ...filters, batch: event.target.value })}
          />
          <Button disabled={busy} onClick={() => void search()}>
            查询
          </Button>
        </div>
      </section>
      {error && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}
      {registrationRunId && (
        <Button variant="secondary" disabled={busy} onClick={() => void retryRegistration()}>
          重试登记
        </Button>
      )}
      <section
        aria-label="库存查询结果"
        className="flex min-h-[300px] min-w-0 flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40 p-4 md:min-h-0 md:flex-1"
      >
        <div className="mb-3 flex shrink-0 items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <h2 className="text-lg font-semibold">
              库存 <span className="text-sm font-normal text-slate-400">{stock.length} 条</span>
            </h2>
            <Button
              variant="secondary"
              disabled={busy || !effective.length}
              onClick={() =>
                setReview({
                  keys: [...selected],
                  selected: [...selected],
                  quantities: { ...quantities },
                  packaging: { ...packaging },
                })
              }
            >
              查看已选（{effective.length}）
            </Button>
            {notice && <span className="text-sm text-amber-300">{notice}</span>}
          </div>
          <Button
            variant="secondary"
            disabled={busy || !effective.length}
            onClick={() => {
              setBatchValue("");
              setBatchOpen(true);
            }}
          >
            批改包装方式
          </Button>
        </div>
        <div className="min-h-0 max-h-[50dvh] flex-1 overflow-auto md:max-h-none">
          {renderStockTable(stock)}
          {searched && !stock.length && !busy && (
            <p className="p-5 text-center text-sm text-slate-400">没有符合条件的库存</p>
          )}
          {!searched && (
            <p className="p-5 text-center text-sm text-slate-400">设置条件后查询库存</p>
          )}
        </div>
      </section>
      <section
        aria-label="打印设置"
        className="flex shrink-0 flex-col gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-4 2xl:flex-row 2xl:items-end"
      >
        <div className="order-2 flex shrink-0 flex-wrap items-center gap-3 2xl:order-1">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeRemainder}
              onChange={(event) => setIncludeRemainder(event.target.checked)}
            />
            打印尾数
          </label>
          <span className="min-w-44 whitespace-nowrap text-sm text-slate-400">
            已选 {effective.length} 条 · 预计 {count()} 张
          </span>
        </div>
        <div className="order-1 flex min-w-0 flex-wrap items-end gap-3 2xl:order-2">
          <div className="flex items-end gap-2">
            <Select
              label="模板"
              className="w-56"
              value={templateId}
              onChange={(event) => setTemplateId(event.target.value)}
            >
              <option value="">选择模板</option>
              {(templates.data ?? []).map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name} ({template.width_mm}×{template.height_mm} mm)
                  {String(template.id) === defaultTemplateId ? " · 默认" : ""}
                </option>
              ))}
            </Select>
            <Button variant="secondary" disabled={!templateId} onClick={setDefaultTemplate}>
              {templateId === defaultTemplateId ? "取消默认" : "设为默认"}
            </Button>
          </div>
          <Select
            label="打印机"
            className="w-56"
            value={printer}
            disabled={!visiblePrinters.length}
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
          <Button
            disabled={busy || !effective.length || !templateId}
            onClick={() => void preview()}
          >
            预览标签
          </Button>
          <Button
            disabled={queryOnly || busy || !effective.length || !templateId || !printer}
            onClick={() => void print()}
          >
            打印
          </Button>
        </div>
      </section>
      <Modal
        open={review !== null}
        wide
        title="核对已选存货"
        onClose={() => setReview(null)}
        footer={
          <>
            <span className="mr-auto self-center text-sm text-slate-400">
              已选 {review?.selected.length ?? 0} 条
            </span>
            <Button variant="secondary" onClick={() => setReview(null)}>
              取消
            </Button>
            <Button
              onClick={() => {
                if (!review) return;
                setSelected(review.selected);
                setQuantities(review.quantities);
                setPackaging(review.packaging);
                setError("");
                setReview(null);
              }}
            >
              确认选择
            </Button>
          </>
        }
      >
        {review &&
          renderStockTable(
            stock.filter((row) => review.keys.includes(keyOf(row))),
            true,
          )}
      </Modal>
      <Modal
        open={batchOpen}
        onClose={() => setBatchOpen(false)}
        title="批改包装方式"
        footer={
          <>
            <Button variant="ghost" onClick={() => setBatchOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => {
                if (
                  !batchValue.trim() ||
                  Number(batchValue) <= 0 ||
                  !Number.isFinite(Number(batchValue))
                ) {
                  setError("包装方式需大于 0");
                  return;
                }
                setPackaging((old) => ({
                  ...old,
                  ...Object.fromEntries(effective.map((row) => [keyOf(row), batchValue])),
                }));
                setBatchOpen(false);
                setError("");
              }}
            >
              应用
            </Button>
          </>
        }
      >
        <Input
          label="包装方式"
          type="number"
          min="0"
          step="any"
          value={batchValue}
          onChange={(event) => setBatchValue(event.target.value)}
        />
      </Modal>
      <Modal
        open={completion !== null}
        onClose={() => setCompletion(null)}
        title="打印完成"
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
                  <p className="text-sm text-slate-400">{previewCount} 张</p>
                </div>
                <Button variant="secondary" onClick={() => setPreviewUrl(null)}>
                  关闭
                </Button>
              </header>
              <div className="min-h-0 flex-1 bg-slate-100 p-3">
                <iframe
                  title="标签预览内容"
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
