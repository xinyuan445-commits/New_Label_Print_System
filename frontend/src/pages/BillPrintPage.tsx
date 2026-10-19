import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { createPortal } from "react-dom";
import { Button } from "../components/ui/Button";
import { PrintPageTabs } from "../components/PrintPageTabs";
import { Input } from "../components/ui/Input";
import { Modal } from "../components/ui/Modal";
import { Select } from "../components/ui/Select";
import { useTemplates } from "../hooks/useTemplates";
import { useMe } from "../hooks/useMe";
import { useLocalPrinters } from "../hooks/useLocalPrinters";
import { ApiError, api } from "../lib/api";
import { BROWSER_PRINTER } from "../lib/browserLabelPrint";
import { ClientPrintError, clientLabelPrint } from "../lib/clientLabelPrint";
import { readCsrfCookie } from "../lib/csrf";
import {
  defaultLocalPrinter,
  readLocalPrinterSettings,
  visibleLocalPrinters,
} from "../lib/localPrinterSettings";

type BillType = { code: string; name: string };
type BillTypesResponse = {
  bill_types: BillType[];
  favorites: string[];
  configured: boolean;
  barcode_account_code: string;
  query_only: boolean;
};
type Bill = { ID: number; 单据号: string; 单据日期: string };
type Detail = {
  明细ID?: string | number;
  已打印数量?: string;
  待打印数量?: string;
  打印状态?: string;
  仓库编码?: string;
  仓库名称?: string | null;
  货位编码?: string;
  货位名称?: string | null;
  存货编码: string;
  存货名称: string;
  数量: string | number;
  单位: string | null;
  批号: string | null;
  包装方式: string | number | null;
};
type PdaLabel = {
  存货编码: string;
  批号: string;
  原标签数量: string;
  标签剩余: string;
  本次数量: string;
  状态: string;
};

const OUTBOUND_TYPES = new Set(["XSCK", "OtherOUT", "CLCK"]);
const MOVEMENT_TYPES = new Set(["DBD", "HWTZ"]);

function canPrintPending(row: Detail): boolean {
  return row.打印状态 !== "待核对" && Number(row.待打印数量) > 0;
}

function detailQuantity(row: Detail, type: string, pending: boolean): string {
  const value = Number(pending ? row.待打印数量 : row.数量);
  return Number.isFinite(value)
    ? (pending && OUTBOUND_TYPES.has(type) ? -value : value).toFixed(2)
    : "";
}

const defaultTemplateKey = (userId: number) => `barcodelabelgen.default-bill-template.v1.${userId}`;

function readDefaultTemplateId(userId: number): string {
  try {
    const value = localStorage.getItem(defaultTemplateKey(userId)) ?? "";
    return /^[1-9]\d*$/.test(value) ? value : "";
  } catch {
    return "";
  }
}

function saveDefaultTemplateId(userId: number, templateId: string): boolean {
  try {
    if (templateId) localStorage.setItem(defaultTemplateKey(userId), templateId);
    else localStorage.removeItem(defaultTemplateKey(userId));
    return true;
  } catch {
    return false;
  }
}

function localDate(offsetDays = 0): string {
  const now = new Date();
  now.setDate(now.getDate() + offsetDays);
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function message(error: unknown): string {
  if (error instanceof ClientPrintError) return error.message;
  if (error instanceof ApiError) {
    if (error.code === "u8_not_configured") return "尚未配置 U8 数据库连接";
    if (error.code === "u8_query_failed") return "U8 查询失败，请检查数据库连接";
    if (error.code === "u8_database_mismatch") return "数据库账套与配置不一致";
    if (error.code === "u8_read_only") return "当前账套仅供查询";
    if (error.code === "invalid_quantity") return "打印数量或包装方式无效，请核对明细";
    if (error.code === "not_inbound_line") return "所选明细不需要生成入库标签";
    if (error.code === "no_labels_for_line") return "有明细未生成标签，请检查尾数设置";
    if (error.code === "too_many_labels") return "一次最多生成 1000 张标签";
    if (error.code === "trace_conflict") return "打印记录已存在或不完整，请联系管理员核对";
    if (error.code === "printer_not_found") return "打印机不可用，请重新选择";
    if (error.code === "printer_failed" || error.code === "print_failed")
      return "打印失败，请检查打印机";
    if (error.code === "file_exists") return "同名标签文件已存在，请核对后重试";
    if (error.code === "trace_registration_failed") return "打印已完成，但记录登记失败";
    if (error.code === "bill_changed") return "单据明细已变化，请重新查询";
    if (error.code === "print_progress_changed") return "打印进度已变化，请重新打开单据";
  }
  return "操作失败，请稍后重试";
}

export function BillPrintPage() {
  const queryClient = useQueryClient();
  const [types, setTypes] = useState<BillTypesResponse | null>(null);
  const [billType, setBillType] = useState("");
  const [code, setCode] = useState("");
  const [startDate, setStartDate] = useState(localDate(-30));
  const [endDate, setEndDate] = useState(localDate());
  const [bills, setBills] = useState<Bill[]>([]);
  const [bill, setBill] = useState<Bill | null>(null);
  const searchRequestId = useRef(0);
  const detailRequestId = useRef(0);
  const resultsRef = useRef<HTMLDivElement>(null);
  const previewCloseRef = useRef<HTMLButtonElement>(null);
  const [resultsHeight, setResultsHeight] = useState<number | null>(null);
  const [details, setDetails] = useState<Detail[]>([]);
  const [selected, setSelected] = useState<number[]>([]);
  const [packaging, setPackaging] = useState<Record<number, string>>({});
  const [batchPackagingOpen, setBatchPackagingOpen] = useState(false);
  const [batchPackagingValue, setBatchPackagingValue] = useState("");
  const [batchPackagingError, setBatchPackagingError] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [defaultTemplateId, setDefaultTemplateId] = useState("");
  const [pendingMode, setPendingMode] = useState(false);
  const [pdaLabels, setPdaLabels] = useState<PdaLabel[]>([]);
  const [pdaOpen, setPdaOpen] = useState(false);
  const [printerSettings, setPrinterSettings] = useState(readLocalPrinterSettings);
  const [selectedPrinter, setSelectedPrinter] = useState("");
  const [includeRemainder, setIncludeRemainder] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [printCompletion, setPrintCompletion] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewCount, setPreviewCount] = useState(0);
  const [registrationRunId, setRegistrationRunId] = useState<string | null>(null);
  const [favoriteDialogOpen, setFavoriteDialogOpen] = useState(false);
  const [favoriteDraft, setFavoriteDraft] = useState<string[]>([]);
  const [favoriteSaving, setFavoriteSaving] = useState(false);
  const [favoriteError, setFavoriteError] = useState("");
  const templates = useTemplates();
  const { data: me } = useMe();
  const userId = me?.id;
  const localPrinters = useLocalPrinters();
  const printerNames = localPrinters.data ?? [];
  const visiblePrinters = [...visibleLocalPrinters(printerNames, printerSettings), BROWSER_PRINTER];

  useEffect(() => {
    if (userId === undefined) return;
    const saved = readDefaultTemplateId(userId);
    setDefaultTemplateId(saved);
    setTemplateId(saved);
  }, [userId]);

  useEffect(() => {
    if (userId === undefined || !templates.data || !defaultTemplateId) return;
    if (templates.data.some((template) => String(template.id) === defaultTemplateId)) return;
    saveDefaultTemplateId(userId, "");
    setDefaultTemplateId("");
    setTemplateId((current) => (current === defaultTemplateId ? "" : current));
  }, [userId, templates.data, defaultTemplateId]);

  useEffect(() => {
    let active = true;
    void api<BillTypesResponse>("/api/u8/bill-types")
      .then(async (data) => {
        if (!active) return;
        setTypes(data);
        const route = new URLSearchParams(window.location.search);
        const requested = route.get("type");
        const type = data.bill_types.some((item) => item.code === requested)
          ? (requested ?? "")
          : (data.favorites[0] ?? data.bill_types[0]?.code ?? "");
        setBillType(type);
        const requestedCode = route.get("code");
        const requestedDate = route.get("date");
        const requestedId = Number(route.get("bill_id"));
        if (
          !requestedCode ||
          !requestedDate ||
          !/^\d{4}-\d{2}-\d{2}$/.test(requestedDate) ||
          !Number.isInteger(requestedId) ||
          requestedId <= 0 ||
          type !== requested
        )
          return;
        setCode(requestedCode);
        setStartDate(requestedDate);
        setEndDate(requestedDate);
        const fromPending = route.get("pending") === "1";
        setPendingMode(fromPending);
        const searchId = ++searchRequestId.current;
        const detailId = ++detailRequestId.current;
        setBusy(true);
        try {
          const params = new URLSearchParams({
            bill_type: type,
            code: requestedCode,
            start_date: requestedDate,
            end_date: requestedDate,
          });
          const pdaParams = new URLSearchParams({ bill_type: type, bill_number: requestedCode });
          const pdaRequest =
            fromPending && MOVEMENT_TYPES.has(type)
              ? api<{ labels: PdaLabel[] }>(`/api/u8/pda-labels?${pdaParams}`)
              : Promise.resolve({ labels: [] as PdaLabel[] });
          const [headers, lines, pda] = await Promise.all([
            api<{ bills: Bill[]; truncated: boolean }>(`/api/u8/bills?${params}`),
            api<{ details: Detail[]; truncated: boolean }>(
              `/api/u8/bills/${type}/${requestedId}/details${fromPending ? `?pending=1&bill_number=${encodeURIComponent(requestedCode)}` : ""}`,
            ),
            pdaRequest,
          ]);
          if (
            !active ||
            searchId !== searchRequestId.current ||
            detailId !== detailRequestId.current
          )
            return;
          const found = headers.bills.find((item) => item.ID === requestedId);
          const target = found ?? {
            ID: requestedId,
            单据号: requestedCode,
            单据日期: requestedDate,
          };
          setBills(found ? headers.bills : [target, ...headers.bills]);
          setBill(target);
          setDetails(
            lines.details.map((item) => ({
              ...item,
              数量: detailQuantity(item, type, fromPending),
            })),
          );
          setPackaging(
            Object.fromEntries(
              lines.details.map((item, index) => [index, String(item.包装方式 ?? "")]),
            ),
          );
          setPdaLabels(pda.labels);
          if (fromPending) {
            setSelected(
              lines.details.flatMap((item, index) => (canPrintPending(item) ? [index] : [])),
            );
          }
          if (headers.truncated || lines.truncated) setNotice("单据数据较多，请核对明细");
        } catch (cause) {
          if (active && searchId === searchRequestId.current) setError(message(cause));
        } finally {
          if (active && searchId === searchRequestId.current) setBusy(false);
        }
      })
      .catch((cause: unknown) => {
        if (active) setError(message(cause));
      });
    return () => {
      active = false;
      searchRequestId.current += 1;
      detailRequestId.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!previewUrl) return;
    const previousOverflow = document.body.style.overflow;
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => previewCloseRef.current?.focus());
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewUrl(null);
    };
    document.addEventListener("keydown", handleEscape);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
      URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  useEffect(() => {
    if (printCompletion === null) return;
    const timer = window.setTimeout(() => setPrintCompletion(null), 3000);
    return () => window.clearTimeout(timer);
  }, [printCompletion]);

  useEffect(() => {
    const names = localPrinters.data ?? [];
    const visible = visibleLocalPrinters(names, printerSettings);
    setSelectedPrinter((current) =>
      visible.includes(current) || current === BROWSER_PRINTER
        ? current
        : defaultLocalPrinter(names, printerSettings) || BROWSER_PRINTER,
    );
  }, [localPrinters.data, printerSettings]);

  useEffect(() => {
    const refreshSettings = () => setPrinterSettings(readLocalPrinterSettings());
    window.addEventListener("storage", refreshSettings);
    return () => window.removeEventListener("storage", refreshSettings);
  }, []);

  useLayoutEffect(() => {
    function fitResults() {
      if (!resultsRef.current || !window.matchMedia("(min-width: 1024px)").matches) {
        setResultsHeight(null);
        return;
      }
      setResultsHeight(
        Math.max(
          260,
          Math.floor(window.innerHeight - resultsRef.current.getBoundingClientRect().top - 72),
        ),
      );
    }
    fitResults();
    window.addEventListener("resize", fitResults);
    return () => window.removeEventListener("resize", fitResults);
  }, [types, error, notice]);

  function chooseBillType(type: string) {
    searchRequestId.current += 1;
    detailRequestId.current += 1;
    setBillType(type);
    setPendingMode(false);
    setPdaLabels([]);
    setBills([]);
    setBill(null);
    setDetails([]);
    setSelected([]);
    setPackaging({});
    setPreviewUrl(null);
    setRegistrationRunId(null);
    setBusy(false);
  }

  function openFavoriteDialog() {
    if (!types) return;
    setFavoriteDraft(types.favorites);
    setFavoriteError("");
    setFavoriteDialogOpen(true);
  }

  function toggleFavorite(type: string) {
    setFavoriteDraft((current) =>
      current.includes(type)
        ? current.filter((item) => item !== type)
        : current.length < 8
          ? [...current, type]
          : current,
    );
  }

  async function saveFavorites() {
    if (!types) return;
    setFavoriteSaving(true);
    setFavoriteError("");
    try {
      const result = await api<{ favorites: string[] }>("/api/u8/favorites", {
        method: "PUT",
        body: JSON.stringify({ bill_types: favoriteDraft }),
      });
      setTypes({ ...types, favorites: result.favorites });
      setFavoriteDialogOpen(false);
    } catch (cause) {
      setFavoriteError(message(cause));
    } finally {
      setFavoriteSaving(false);
    }
  }

  async function searchBills() {
    if (!billType) return;
    const requestId = ++searchRequestId.current;
    detailRequestId.current += 1;
    setPendingMode(false);
    setPdaLabels([]);
    setBusy(true);
    setError("");
    setNotice("");
    setBills([]);
    setBill(null);
    setDetails([]);
    setSelected([]);
    setPackaging({});
    setPreviewUrl(null);
    setRegistrationRunId(null);
    try {
      const params = new URLSearchParams({
        bill_type: billType,
        code,
        start_date: startDate,
        end_date: endDate,
      });
      const result = await api<{ bills: Bill[]; truncated: boolean }>(`/api/u8/bills?${params}`);
      if (requestId !== searchRequestId.current) return;
      setBills(result.bills);
      if (result.truncated) setNotice("仅显示前 200 条，请缩小查询范围");
    } catch (cause) {
      if (requestId === searchRequestId.current) setError(message(cause));
    } finally {
      if (requestId === searchRequestId.current) setBusy(false);
    }
  }

  async function openBill(row: Bill) {
    const requestId = ++detailRequestId.current;
    setBill(row);
    setPdaLabels([]);
    setDetails([]);
    setSelected([]);
    setPackaging({});
    setPreviewUrl(null);
    setRegistrationRunId(null);
    setBusy(true);
    setError("");
    try {
      const result = await api<{ details: Detail[]; truncated: boolean }>(
        `/api/u8/bills/${billType}/${row.ID}/details${pendingMode ? `?pending=1&bill_number=${encodeURIComponent(row.单据号)}` : ""}`,
      );
      if (requestId !== detailRequestId.current) return;
      setDetails(
        result.details.map((item) => ({
          ...item,
          数量: detailQuantity(item, billType, pendingMode),
        })),
      );
      setPackaging(
        Object.fromEntries(
          result.details.map((item, index) => [index, String(item.包装方式 ?? "")]),
        ),
      );
      if (pendingMode)
        setSelected(
          result.details.flatMap((item, index) => (canPrintPending(item) ? [index] : [])),
        );
      if (result.truncated) setNotice("明细较多，仅显示前 1000 条");
    } catch (cause) {
      if (requestId === detailRequestId.current) setError(message(cause));
    } finally {
      if (requestId === detailRequestId.current) setBusy(false);
    }
  }

  function validateQuantity(index: number) {
    const value = Number(details[index]?.数量);
    if (pendingMode && Math.abs(value) > Number(details[index]?.待打印数量)) {
      setError("打印数量不能超过待打印数量");
      return;
    }
    const invalid =
      !String(details[index]?.数量 ?? "").trim() ||
      !Number.isFinite(value) ||
      (OUTBOUND_TYPES.has(billType) ? value === 0 : value <= 0);
    if (invalid) {
      setDetails((current) =>
        current.map((item, rowIndex) => (rowIndex === index ? { ...item, 数量: "" } : item)),
      );
      setError(OUTBOUND_TYPES.has(billType) ? "【数量】不能为 0" : "【数量】必须是大于 0 的数字");
      return;
    }
    setDetails((current) =>
      current.map((item, rowIndex) =>
        rowIndex === index ? { ...item, 数量: value.toFixed(2) } : item,
      ),
    );
    setError("");
  }

  function validatePackaging(index: number) {
    const value = Number(packaging[index]);
    if (!String(packaging[index] ?? "").trim() || !Number.isFinite(value) || value <= 0) {
      setPackaging((current) => ({ ...current, [index]: "" }));
      setError("【包装方式】必须是大于 0 的数字");
      return;
    }
    setError("");
  }

  function applyBatchPackaging() {
    const value = batchPackagingValue.trim();
    const amount = Number(value);
    if (!value || !Number.isFinite(amount) || amount <= 0) {
      setBatchPackagingError("【包装方式】必须是大于 0 的数字");
      return;
    }
    const selectedRows = new Set(effectiveDetailIndexes());
    setPackaging((current) => ({
      ...current,
      ...Object.fromEntries([...selectedRows].map((index) => [index, value])),
    }));
    setBatchPackagingOpen(false);
    setBatchPackagingValue("");
    setBatchPackagingError("");
    setError("");
  }

  function effectiveDetailIndexes(): number[] {
    const eligible = eligibleDetailIndexes();
    return selected.length > 0 ? selected.filter((index) => eligible.includes(index)) : eligible;
  }

  function eligibleDetailIndexes(): number[] {
    return details.flatMap((row, index) => (!pendingMode || canPrintPending(row) ? [index] : []));
  }

  function labelCount(): number {
    const indexes = effectiveDetailIndexes();
    return indexes.reduce((total, index) => {
      const rawQty = Number(details[index]?.数量 ?? 0);
      const qty = OUTBOUND_TYPES.has(billType) && rawQty < 0 ? -rawQty : rawQty;
      const pack = Number(packaging[index]);
      if (!Number.isFinite(qty) || !Number.isFinite(pack) || qty <= 0 || pack <= 0) return total;
      const full = Math.floor(qty / pack);
      return total + full + (includeRemainder && qty - full * pack > 0.001 ? 1 : 0);
    }, 0);
  }

  function toggleDefaultTemplate() {
    if (userId === undefined || !templateId) return;
    const next = defaultTemplateId === templateId ? "" : templateId;
    if (!saveDefaultTemplateId(userId, next)) {
      setError("默认模板保存失败");
      return;
    }
    setDefaultTemplateId(next);
    setError("");
  }

  async function preview() {
    if (!templateId || details.length === 0 || !bill) return;
    const indexes = effectiveDetailIndexes();
    if (indexes.length === 0) {
      setError("请选择需要打印的明细");
      return;
    }
    const rows: Array<Record<string, string>> = [];
    for (const index of indexes) {
      const row = details[index];
      const pack = Number(packaging[index]);
      const rawQty = Number(row.数量);
      const qty = OUTBOUND_TYPES.has(billType) && rawQty < 0 ? -rawQty : rawQty;
      if (!Number.isFinite(pack) || pack <= 0 || !Number.isFinite(qty) || qty <= 0) {
        setError(`第 ${index + 1} 条明细的数量或包装方式无效`);
        return;
      }
      const full = Math.floor(qty / pack);
      const remainder = qty - full * pack;
      const hasRemainder = includeRemainder && remainder > 0.001;
      if (rows.length + full + (hasRemainder ? 1 : 0) > 1000) {
        setError("一次最多预览 1000 张标签，请缩小明细范围");
        return;
      }
      const quantities = Array.from({ length: full }, () => pack);
      if (hasRemainder) quantities.push(remainder);
      for (const amount of quantities) {
        const labelQty = amount.toFixed(2);
        const sn = `PREVIEW-${rows.length + 1}`;
        rows.push({
          账套名: "科米龙",
          单据编码: bill.单据号,
          行号: String(index + 1),
          物料编码: row.存货编码,
          物料名称: row.存货名称,
          批号: row.批号 ?? "",
          数量: labelQty,
          单位: row.单位 ?? "",
          sn,
          条码: `${types?.barcode_account_code ?? "008"}|${row.存货编码}|${row.批号 ?? ""}|${labelQty}|${sn}`,
        });
      }
    }
    if (rows.length === 0) {
      setError("没有可预览的标签");
      return;
    }
    setBusy(true);
    setError("");
    setRegistrationRunId(null);
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

  async function printLabels() {
    if (!bill || !templateId || !selectedPrinter) return;
    const indexes = effectiveDetailIndexes();
    if (indexes.length === 0) {
      setError("请选择需要打印的明细");
      return;
    }
    const lines = indexes.map((index) => ({
      index,
      detail_id: details[index]?.明细ID === undefined ? undefined : String(details[index].明细ID),
      item_code: details[index]?.存货编码,
      batch: details[index]?.批号 ?? "",
      quantity: Math.abs(Number(details[index]?.数量)),
      packaging: Number(packaging[index]),
    }));
    if (
      lines.some(
        (line) =>
          !Number.isFinite(line.quantity) ||
          line.quantity <= 0 ||
          !Number.isFinite(line.packaging) ||
          line.packaging <= 0,
      )
    ) {
      setError("打印数量或包装方式无效，请核对明细");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await clientLabelPrint(
        "/api/u8/print",
        {
          bill_type: billType,
          bill_id: bill.ID,
          bill_number: bill.单据号,
          bill_date: String(bill.单据日期).slice(0, 10),
          template_id: Number(templateId),
          printer: selectedPrinter,
          lines,
          include_remainder: includeRemainder,
          pending_only: pendingMode,
        },
        me!.id,
      );
      setRegistrationRunId(null);
      setNotice("");
      setPrintCompletion(
        result.output_dir
          ? `已保存 ${result.printed} 张标签到 ${result.output_dir}`
          : `已提交 ${result.printed} 张标签到 ${selectedPrinter}`,
      );
      void queryClient.invalidateQueries({ queryKey: ["u8", "pending-bills"] });
      if (pendingMode) {
        const progress = await api<{ details: Detail[]; truncated: boolean }>(
          `/api/u8/bills/${billType}/${bill.ID}/details?pending=1&bill_number=${encodeURIComponent(bill.单据号)}`,
        );
        setDetails(
          progress.details.map((row) => ({ ...row, 数量: detailQuantity(row, billType, true) })),
        );
        setSelected(
          progress.details.flatMap((row, index) => (canPrintPending(row) ? [index] : [])),
        );
      }
    } catch (cause) {
      setError(message(cause));
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
        {
          method: "POST",
        },
      );
      setRegistrationRunId(null);
      setNotice(`已登记 ${result.registered} 张标签`);
      void queryClient.invalidateQueries({ queryKey: ["u8", "pending-bills"] });
    } catch (cause) {
      setError(message(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">单据打印</h1>
        <p className="mt-1 text-xs text-slate-400">当前账号：{me?.email} · 常用单据按账号保存</p>
      </header>
      <PrintPageTabs />
      {localPrinters.isError && (
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

      {types && !types.configured && (
        <p className="rounded-md border border-amber-800 bg-amber-950/30 px-4 py-3 text-sm text-amber-300">
          尚未配置 U8 数据库连接
        </p>
      )}
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
      {notice && <p className="text-sm text-amber-300">{notice}</p>}

      <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <span className="mr-2 text-sm text-slate-400">常用单据</span>
          {types?.favorites.map((favorite) => (
            <button
              key={favorite}
              className="rounded-full border border-indigo-600 px-3 py-1 text-sm text-indigo-200"
              onClick={() => chooseBillType(favorite)}
            >
              {types.bill_types.find((item) => item.code === favorite)?.name ?? favorite}
            </button>
          ))}
          <button
            type="button"
            className="ml-auto text-sm text-indigo-300 hover:text-indigo-200"
            onClick={openFavoriteDialog}
            disabled={!types}
          >
            设置常用单据
          </button>
        </div>
        <div className="grid gap-3 md:grid-cols-[minmax(180px,1fr)_minmax(180px,1fr)_150px_150px_auto] md:items-end">
          <Select
            label="单据类型"
            value={billType}
            onChange={(event) => chooseBillType(event.target.value)}
          >
            {(types?.bill_types ?? []).map((item) => (
              <option key={item.code} value={item.code}>
                {item.name}
              </option>
            ))}
          </Select>
          <Input label="单据号" value={code} onChange={(event) => setCode(event.target.value)} />
          <Input
            label="开始日期"
            type="date"
            value={startDate}
            onChange={(event) => setStartDate(event.target.value)}
          />
          <Input
            label="结束日期"
            type="date"
            value={endDate}
            onChange={(event) => setEndDate(event.target.value)}
          />
          <Button disabled={busy || !types?.configured} onClick={() => void searchBills()}>
            查询
          </Button>
        </div>
      </section>

      <Modal
        open={favoriteDialogOpen}
        onClose={() => {
          if (!favoriteSaving) setFavoriteDialogOpen(false);
        }}
        title="设置常用单据"
        footer={
          <>
            <Button
              variant="ghost"
              disabled={favoriteSaving}
              onClick={() => setFavoriteDialogOpen(false)}
            >
              取消
            </Button>
            <Button disabled={favoriteSaving} onClick={() => void saveFavorites()}>
              {favoriteSaving ? "保存中…" : "保存"}
            </Button>
          </>
        }
      >
        <p className="mb-3 text-sm text-slate-400">已选择 {favoriteDraft.length}/8</p>
        <div className="grid max-h-72 gap-2 overflow-y-auto sm:grid-cols-2">
          {types?.bill_types.map((item) => {
            const checked = favoriteDraft.includes(item.code);
            return (
              <label
                key={item.code}
                className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-700 px-3 py-2 text-sm hover:bg-slate-800"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={!checked && favoriteDraft.length >= 8}
                  onChange={() => toggleFavorite(item.code)}
                />
                {item.name}
              </label>
            );
          })}
        </div>
        {favoriteError && (
          <p role="alert" className="mt-3 text-sm text-rose-400">
            {favoriteError}
          </p>
        )}
      </Modal>

      <Modal
        open={printCompletion !== null}
        onClose={() => setPrintCompletion(null)}
        title="打印完成"
        footer={<Button onClick={() => setPrintCompletion(null)}>确定</Button>}
      >
        <p className="break-all text-sm text-slate-200">{printCompletion}</p>
      </Modal>

      <div
        ref={resultsRef}
        style={resultsHeight === null ? undefined : { height: resultsHeight }}
        className="grid min-h-0 gap-6 lg:grid-cols-[minmax(280px,2fr)_minmax(0,5fr)]"
      >
        <section className="flex min-h-0 min-w-0 max-h-[50dvh] flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40 p-5 lg:max-h-none">
          <h2 className="mb-3 shrink-0 text-lg font-semibold">单据</h2>
          {bills.length === 0 ? (
            <p className="text-sm text-slate-500">暂无单据</p>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full text-left text-sm">
                <thead className="sticky top-0 bg-slate-900 text-slate-400">
                  <tr>
                    <th className="p-2">单据号</th>
                    <th className="p-2">日期</th>
                  </tr>
                </thead>
                <tbody>
                  {bills.map((row) => (
                    <tr
                      key={row.ID}
                      tabIndex={0}
                      aria-selected={bill?.ID === row.ID}
                      className={`cursor-pointer border-t border-slate-800 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400 ${bill?.ID === row.ID ? "bg-indigo-950/50" : ""}`}
                      onClick={() => void openBill(row)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          void openBill(row);
                        }
                      }}
                    >
                      <td className="p-2">{row.单据号}</td>
                      <td className="p-2">{String(row.单据日期).slice(0, 10)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="flex min-h-0 min-w-0 max-h-[50dvh] flex-col overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40 p-5 lg:max-h-none">
          <div className="mb-3 flex shrink-0 flex-wrap items-center justify-between gap-2">
            <h2 className="text-lg font-semibold">{bill ? `${bill.单据号} · 明细` : "明细"}</h2>
            <div className="flex items-center gap-2">
              {pendingMode && MOVEMENT_TYPES.has(billType) && (
                <Button variant="secondary" onClick={() => setPdaOpen(true)}>
                  PDA 标签记录（{pdaLabels.length}）
                </Button>
              )}
              <Button
                variant="secondary"
                disabled={details.length === 0}
                onClick={() => {
                  setBatchPackagingValue("");
                  setBatchPackagingError("");
                  setBatchPackagingOpen(true);
                }}
              >
                批改包装方式
              </Button>
            </div>
          </div>
          {!bill ? (
            <p className="text-sm text-slate-500">请选择单据</p>
          ) : details.length === 0 ? (
            <p className="text-sm text-slate-500">{busy ? "加载中…" : "暂无明细"}</p>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto">
              <table className="w-full min-w-[920px] text-left text-sm">
                <thead className="sticky top-0 bg-slate-900 text-slate-400">
                  <tr>
                    <th className="p-2">
                      <label className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          aria-label="全选明细"
                          checked={
                            selected.length > 0 &&
                            selected.length === eligibleDetailIndexes().length
                          }
                          onChange={(event) =>
                            setSelected(event.target.checked ? eligibleDetailIndexes() : [])
                          }
                        />
                        选择
                      </label>
                    </th>
                    <th className="p-2">仓库名称</th>
                    <th className="p-2">货位名称</th>
                    <th className="p-2">存货编码</th>
                    <th className="p-2">存货名称</th>
                    <th className="p-2 text-right">{pendingMode ? "本次打印数量" : "数量"}</th>
                    <th className="p-2">单位</th>
                    <th className="p-2">批号</th>
                    <th className="p-2">包装方式</th>
                    {pendingMode && (
                      <>
                        <th className="p-2">已打印</th>
                        <th className="p-2">待打印</th>
                        <th className="p-2">状态</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody>
                  {details.map((row, index) => (
                    <tr key={`${row.存货编码}-${index}`} className="border-t border-slate-800">
                      <td className="p-2">
                        <input
                          type="checkbox"
                          disabled={pendingMode && !canPrintPending(row)}
                          aria-label={`选择第 ${index + 1} 条明细`}
                          checked={selected.includes(index)}
                          onChange={(event) =>
                            setSelected((old) =>
                              event.target.checked
                                ? [...old, index]
                                : old.filter((item) => item !== index),
                            )
                          }
                        />
                      </td>
                      <td className="p-2">{row.仓库名称}</td>
                      <td className="p-2">{row.货位名称}</td>
                      <td className="p-2">{row.存货编码}</td>
                      <td className="p-2">{row.存货名称}</td>
                      <td className="p-2 text-right">
                        <input
                          className="w-28 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-right"
                          aria-label={`第 ${index + 1} 条明细数量`}
                          type="number"
                          min={OUTBOUND_TYPES.has(billType) ? undefined : "0"}
                          step="any"
                          value={row.数量}
                          onChange={(event) =>
                            setDetails((current) =>
                              current.map((item, rowIndex) =>
                                rowIndex === index ? { ...item, 数量: event.target.value } : item,
                              ),
                            )
                          }
                          onBlur={() => validateQuantity(index)}
                        />
                      </td>
                      <td className="p-2">{row.单位}</td>
                      <td className="p-2">{row.批号}</td>
                      <td className="p-2">
                        <input
                          className="w-24 rounded border border-slate-700 bg-slate-900 px-2 py-1"
                          aria-label={`第 ${index + 1} 条明细包装方式`}
                          type="number"
                          min="0"
                          step="any"
                          value={packaging[index] ?? ""}
                          onChange={(event) =>
                            setPackaging((old) => ({ ...old, [index]: event.target.value }))
                          }
                          onBlur={() => validatePackaging(index)}
                        />
                      </td>
                      {pendingMode && (
                        <>
                          <td className="p-2">{row.已打印数量}</td>
                          <td className="p-2">{row.待打印数量}</td>
                          <td className="whitespace-nowrap p-2">{row.打印状态}</td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {bill && pendingMode && MOVEMENT_TYPES.has(billType) && (
            <p className="mt-3 text-sm text-amber-300">请核对 PDA 标签记录和需要补打的明细。</p>
          )}
          {bill && (
            <div className="mt-4 flex shrink-0 flex-wrap items-end gap-4">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={includeRemainder}
                  onChange={(event) => setIncludeRemainder(event.target.checked)}
                />
                打印尾数
              </label>
              <span className="text-sm text-slate-400">
                预计 {labelCount()} 张
                {selected.length === 0 ? (pendingMode ? "（待打印明细）" : "（全部明细）") : ""}
              </span>
              <div className="flex items-end gap-2">
                <Select
                  label="模板"
                  className="min-w-48"
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
                <Button
                  variant="secondary"
                  disabled={
                    userId === undefined ||
                    !templateId ||
                    !templates.data?.some((template) => String(template.id) === templateId)
                  }
                  onClick={toggleDefaultTemplate}
                >
                  {templateId === defaultTemplateId ? "取消默认" : "设为默认"}
                </Button>
              </div>
              <Select
                label="打印机"
                className="min-w-56 max-w-72"
                value={selectedPrinter}
                disabled={visiblePrinters.length === 0}
                onChange={(event) => setSelectedPrinter(event.target.value)}
              >
                {visiblePrinters.length === 0 && (
                  <option value="">
                    {localPrinters.isPending
                      ? "读取中…"
                      : localPrinters.isError
                        ? "无法读取打印机"
                        : "没有可选打印机"}
                  </option>
                )}
                {visiblePrinters.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </Select>
              <Button
                disabled={!templateId || details.length === 0 || busy}
                onClick={() => void preview()}
              >
                预览标签
              </Button>
              <Button
                disabled={
                  types?.query_only ||
                  !templateId ||
                  !selectedPrinter ||
                  details.length === 0 ||
                  busy
                }
                onClick={() => void printLabels()}
              >
                打印
              </Button>
            </div>
          )}
        </section>
      </div>

      <Modal
        open={batchPackagingOpen}
        onClose={() => setBatchPackagingOpen(false)}
        title="批改包装方式"
        footer={
          <>
            <Button variant="ghost" onClick={() => setBatchPackagingOpen(false)}>
              取消
            </Button>
            <Button onClick={applyBatchPackaging}>应用</Button>
          </>
        }
      >
        <p className="mb-3 text-sm text-slate-400">
          应用到 {effectiveDetailIndexes().length} 条明细
        </p>
        <Input
          label="包装方式"
          type="number"
          min="0"
          step="any"
          value={batchPackagingValue}
          onChange={(event) => {
            setBatchPackagingValue(event.target.value);
            setBatchPackagingError("");
          }}
          error={batchPackagingError}
        />
      </Modal>

      <Modal
        open={pdaOpen}
        onClose={() => setPdaOpen(false)}
        title="PDA 标签记录"
        footer={<Button onClick={() => setPdaOpen(false)}>关闭</Button>}
      >
        {pdaLabels.length === 0 ? (
          <p className="text-sm text-slate-400">未找到 PDA 标签记录，请核对单据。</p>
        ) : (
          <div className="max-h-[55vh] overflow-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead className="text-slate-400">
                <tr>
                  <th className="p-2">存货编码</th>
                  <th className="p-2">批号</th>
                  <th className="p-2">原标签数量</th>
                  <th className="p-2">标签剩余</th>
                  <th className="p-2">本次数量</th>
                  <th className="p-2">状态</th>
                </tr>
              </thead>
              <tbody>
                {pdaLabels.map((item, index) => (
                  <tr
                    key={`${item.存货编码}-${item.批号}-${index}`}
                    className="border-t border-slate-800"
                  >
                    <td className="p-2">{item.存货编码}</td>
                    <td className="p-2">{item.批号}</td>
                    <td className="p-2">{item.原标签数量 || "—"}</td>
                    <td className="p-2">{item.标签剩余 || "—"}</td>
                    <td className="p-2">{item.本次数量 || "—"}</td>
                    <td className="p-2">{item.状态}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Modal>

      {previewUrl &&
        createPortal(
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 p-2 sm:p-5">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="bill-preview-title"
              className="flex h-full w-full max-w-[1600px] flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl"
            >
              <header className="flex shrink-0 items-center justify-between gap-4 border-b border-slate-800 px-4 py-3 sm:px-5">
                <div className="min-w-0">
                  <h2 id="bill-preview-title" className="text-lg font-semibold text-slate-100">
                    标签预览
                  </h2>
                  <p className="truncate text-sm text-slate-400">
                    {bill?.单据号} · {previewCount} 张
                  </p>
                </div>
                <button
                  ref={previewCloseRef}
                  type="button"
                  onClick={() => setPreviewUrl(null)}
                  className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-100 hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                >
                  关闭
                </button>
              </header>
              <div className="min-h-0 flex-1 bg-slate-100 p-2 sm:p-3">
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
