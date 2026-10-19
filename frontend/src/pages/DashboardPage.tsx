import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useLocalPrinters } from "../hooks/useLocalPrinters";
import { useMe } from "../hooks/useMe";
import type { TemplateSummary } from "../hooks/useTemplates";
import { api } from "../lib/api";
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
  query_only: boolean;
};
type PendingBill = {
  bill_type: string;
  ID: number;
  单据号: string;
  单据日期: string;
  原因: string;
  待打印明细数: number;
};
type PendingResponse = { bills: PendingBill[]; total: number; truncated: boolean };

function defaultTemplateId(userId: number): string {
  try {
    return localStorage.getItem(`barcodelabelgen.default-bill-template.v1.${userId}`) ?? "";
  } catch {
    return "";
  }
}

function billLink(bill: PendingBill): string {
  const params = new URLSearchParams({
    type: bill.bill_type,
    code: bill.单据号,
    date: bill.单据日期.slice(0, 10),
    bill_id: String(bill.ID),
    pending: "1",
  });
  return `/bills?${params}`;
}

export function DashboardPage() {
  const { data: me } = useMe();
  const showBills = Boolean(me?.permissions.bills && me.visibility.bills);
  const billTypes = useQuery({
    queryKey: ["u8", "bill-types"],
    queryFn: () => api<BillTypesResponse>("/api/u8/bill-types"),
    enabled: showBills,
  });
  const pending = useQuery({
    queryKey: ["u8", "pending-bills"],
    queryFn: () => api<PendingResponse>("/api/u8/pending-bills"),
    enabled: showBills,
  });
  const templates = useQuery({
    queryKey: ["templates", "all"],
    queryFn: () => api<{ templates: TemplateSummary[] }>("/api/templates").then((r) => r.templates),
    enabled: showBills,
  });
  const printers = useLocalPrinters({ enabled: showBills });
  const settings = readLocalPrinterSettings();
  const printerNames = visibleLocalPrinters(printers.data ?? [], settings);
  const printerName = defaultLocalPrinter(printers.data ?? [], settings);
  const selectedTemplate = templates.data?.find(
    (item) => String(item.id) === defaultTemplateId(me?.id ?? 0),
  );
  const typeNames = new Map(billTypes.data?.bill_types.map((item) => [item.code, item.name]));
  const links = [
    me?.permissions.templates && me.visibility.templates && { to: "/templates", label: "模板管理" },
    me?.permissions.printers && me.visibility.printers && { to: "/devices", label: "打印机管理" },
    me?.permissions.library && me.visibility.library && { to: "/library", label: "模板库" },
    me?.permissions.history && me.visibility.history && { to: "/history", label: "生成记录" },
    me?.role === "admin" && me.visibility.users && { to: "/admin/users", label: "用户管理" },
  ].filter((item): item is { to: string; label: string } => Boolean(item));

  return (
    <div className="w-full space-y-7">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-800 pb-6">
        <div>
          <p className="mb-2 text-sm text-slate-400">标签打印工作台</p>
          <h1 className="text-3xl font-semibold text-slate-100">待打印单据</h1>
          {showBills && (
            <p className="mt-2 text-sm text-slate-400">
              近 30 天 · 全部单据类型 · 未打印完成
              {billTypes.data?.query_only ? " · 008 账套（仅查询）" : ""}
            </p>
          )}
        </div>
        {showBills && (
          <Link
            to="/bills"
            className="rounded-md bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-500"
          >
            查询单据
          </Link>
        )}
      </header>

      {showBills ? (
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1.9fr)_minmax(360px,0.85fr)]">
          <section className="min-w-0 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/40">
            <div className="flex flex-wrap items-center justify-between gap-4 px-7 py-6">
              <div className="flex items-baseline gap-4">
                <h2 className="text-xl font-semibold text-slate-100">待打印清单</h2>
                <span className="text-3xl font-semibold tabular-nums text-indigo-300">
                  {pending.data?.total ?? "—"}
                </span>
                <span className="text-sm text-slate-400">张单据</span>
              </div>
              <button
                type="button"
                onClick={() => void pending.refetch()}
                disabled={pending.isFetching}
                className="text-sm text-indigo-400 hover:text-indigo-300 disabled:opacity-50"
              >
                {pending.isFetching ? "读取中…" : "刷新"}
              </button>
            </div>

            {pending.isError ? (
              <p className="border-t border-slate-800 px-7 py-8 text-sm text-rose-400">
                待打印单据读取失败，请检查 U8 连接。
              </p>
            ) : pending.data?.bills.length ? (
              <div className="max-h-[650px] overflow-auto border-t border-slate-800">
                <table className="w-full min-w-[640px] text-left">
                  <thead className="sticky top-0 bg-slate-900 text-sm text-slate-400">
                    <tr>
                      <th className="px-7 py-4 font-medium">单据日期</th>
                      <th className="px-5 py-4 font-medium">单据类型</th>
                      <th className="px-5 py-4 font-medium">单据号</th>
                      <th className="px-5 py-4 font-medium">状态</th>
                      <th className="px-5 py-4 font-medium">待打印明细</th>
                      <th className="px-7 py-4 text-right font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pending.data.bills.map((bill) => (
                      <tr
                        key={`${bill.bill_type}-${bill.ID}`}
                        className="border-t border-slate-800 text-base text-slate-100"
                      >
                        <td className="whitespace-nowrap px-7 py-5">
                          {bill.单据日期.slice(0, 10)}
                        </td>
                        <td className="px-5 py-5">
                          {typeNames.get(bill.bill_type) ?? bill.bill_type}
                        </td>
                        <td className="px-5 py-5 font-medium">{bill.单据号}</td>
                        <td className="px-5 py-5 text-sm text-amber-400">{bill.原因}</td>
                        <td className="px-5 py-5 tabular-nums">{bill.待打印明细数}</td>
                        <td className="px-7 py-5 text-right">
                          <Link
                            to={billLink(bill)}
                            className="font-medium text-indigo-400 hover:text-indigo-300"
                          >
                            打开单据 →
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="border-t border-slate-800 px-7 py-12">
                <p className="text-base text-slate-300">
                  {pending.isPending ? "正在读取待打印单据…" : "近 30 天没有待打印单据。"}
                </p>
              </div>
            )}
            {pending.data?.truncated && (
              <p className="border-t border-slate-800 px-7 py-3 text-sm text-slate-400">
                仅显示最近 100 张单据
              </p>
            )}
          </section>

          <aside className="space-y-6">
            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-6">
              <h2 className="mb-5 text-xl font-semibold text-slate-100">打印准备</h2>
              <div className="space-y-5">
                <div>
                  <p className="text-sm text-slate-400">默认模板</p>
                  <p className="mt-1 break-words text-base font-medium text-slate-100">
                    {templates.isPending ? "读取中…" : (selectedTemplate?.name ?? "未设置")}
                  </p>
                </div>
                <div className="border-t border-slate-800 pt-5">
                  <p className="text-sm text-slate-400">默认打印机</p>
                  <p className="mt-1 break-words text-base font-medium text-slate-100">
                    {printers.isPending ? "读取中…" : printerName || "未设置"}
                  </p>
                  {printers.data && (
                    <p className="mt-1 text-sm text-slate-400">当前显示 {printerNames.length} 台</p>
                  )}
                </div>
              </div>
            </section>

            <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-6">
              <div className="mb-5 flex items-center justify-between gap-3">
                <h2 className="text-xl font-semibold text-slate-100">常用单据</h2>
                <Link to="/bills" className="text-sm text-indigo-400 hover:text-indigo-300">
                  管理
                </Link>
              </div>
              <div className="grid grid-cols-2 gap-3">
                {(billTypes.data?.favorites ?? []).map((code) => (
                  <Link
                    key={code}
                    to={`/bills?type=${encodeURIComponent(code)}`}
                    className="rounded-md border border-slate-800 px-4 py-4 text-base text-slate-100 hover:border-indigo-700 hover:bg-slate-800"
                  >
                    {typeNames.get(code) ?? code}
                  </Link>
                ))}
              </div>
              {billTypes.isPending && <p className="text-sm text-slate-400">读取中…</p>}
              {billTypes.data?.favorites.length === 0 && (
                <p className="text-sm text-slate-400">尚未选择常用单据</p>
              )}
            </section>

            {links.length > 0 && (
              <section className="rounded-lg border border-slate-800 bg-slate-900/40 p-6">
                <h2 className="mb-4 text-xl font-semibold text-slate-100">页面入口</h2>
                <div className="grid grid-cols-2 gap-x-5">
                  {links.map((item) => (
                    <Link
                      key={item.to}
                      to={item.to}
                      className="border-t border-slate-800 py-4 text-sm text-slate-300 hover:text-indigo-300"
                    >
                      {item.label} →
                    </Link>
                  ))}
                </div>
              </section>
            )}
          </aside>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {links.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-lg border border-slate-800 bg-slate-900/40 p-6 text-lg font-medium text-slate-100 hover:border-indigo-700"
            >
              {item.label} →
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
