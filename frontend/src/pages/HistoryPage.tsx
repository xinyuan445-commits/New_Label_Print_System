/** Generated files can be opened directly from their history row. */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Button } from "../components/ui/Button";
import {
  type GeneratedFile,
  downloadHistoryFile,
  fetchHistoryFile,
  useDeleteGeneratedFile,
  useHistory,
} from "../hooks/useGeneratedFiles";

type HistoryPreview = { file: GeneratedFile; url?: string; text?: string };

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function HistoryPage() {
  const { t } = useTranslation();
  const { data: files, isLoading } = useHistory();
  const del = useDeleteGeneratedFile();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [preview, setPreview] = useState<HistoryPreview | null>(null);
  const [error, setError] = useState("");
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!preview) return;
    const previousOverflow = document.body.style.overflow;
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    const frame = window.requestAnimationFrame(() => closeRef.current?.focus());
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreview(null);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
      if (preview.url) URL.revokeObjectURL(preview.url);
    };
  }, [preview]);

  async function openPreview(file: GeneratedFile) {
    if (busyId !== null) return;
    setBusyId(file.id);
    setError("");
    try {
      const blob = await fetchHistoryFile(file);
      if (file.kind === "pdf") {
        setPreview({ file, url: URL.createObjectURL(blob) });
      } else {
        setPreview({ file, text: await blob.text() });
      }
    } catch {
      setError(t("historyPage.previewFailed"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">{t("nav.history")}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">{t("historyPage.intro")}</p>
      </header>

      {isLoading && <p className="text-slate-400">{t("common.loading")}</p>}
      {error && (
        <p role="alert" className="text-sm text-rose-400">
          {error}
        </p>
      )}

      {files && files.length === 0 && (
        <p className="rounded-lg border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400">
          {t("historyPage.empty")}
        </p>
      )}

      {files && files.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-800">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-left text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-4 py-3">{t("historyPage.template")}</th>
                <th className="px-4 py-3">{t("historyPage.type")}</th>
                <th className="px-4 py-3">{t("historyPage.labels")}</th>
                <th className="px-4 py-3">{t("historyPage.size")}</th>
                <th className="px-4 py-3">{t("historyPage.generatedAt")}</th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 bg-slate-900/30">
              {files.map((f: GeneratedFile) => (
                <tr
                  key={f.id}
                  tabIndex={0}
                  onClick={() => void openPreview(f)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      void openPreview(f);
                    }
                  }}
                  className="cursor-pointer hover:bg-slate-800/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-indigo-400"
                >
                  <td className="px-4 py-3 font-medium text-slate-100">{f.template_name}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    {f.kind.toUpperCase()} ·{" "}
                    {f.mode === "bill"
                      ? t("historyPage.bill")
                      : f.mode === "stock"
                        ? "存货打印"
                        : f.mode === "reprint"
                          ? "标签补打"
                          : f.mode === "series"
                            ? t("historyPage.series")
                            : t("historyPage.single")}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">{f.row_count ?? "1"}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{formatBytes(f.size_bytes)}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    {new Date(f.created_at).toLocaleString()}
                  </td>
                  <td className="space-x-2 px-4 py-3 text-right">
                    <Button
                      variant="secondary"
                      disabled={busyId === f.id}
                      onClick={(event) => {
                        event.stopPropagation();
                        setBusyId(f.id);
                        void downloadHistoryFile(f)
                          .catch(() => setError(t("historyPage.downloadFailed")))
                          .finally(() => setBusyId(null));
                      }}
                    >
                      {t("historyPage.download")}
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={(event) => {
                        event.stopPropagation();
                        if (window.confirm(t("historyPage.confirmDelete"))) del.mutate(f.id);
                      }}
                    >
                      {t("common.delete")}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {preview &&
        createPortal(
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 p-2 sm:p-5">
            <section
              role="dialog"
              aria-modal="true"
              aria-labelledby="history-preview-title"
              className="flex h-full w-full max-w-[1600px] flex-col overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl"
            >
              <header className="flex shrink-0 items-center justify-between gap-4 border-b border-slate-800 px-4 py-3 sm:px-5">
                <div className="min-w-0">
                  <h2
                    id="history-preview-title"
                    className="truncate text-lg font-semibold text-slate-100"
                  >
                    {preview.file.download_name}
                  </h2>
                  <p className="text-sm text-slate-400">
                    {preview.file.kind.toUpperCase()} · {preview.file.row_count ?? 1}{" "}
                    {t("historyPage.labels")}
                  </p>
                </div>
                <button
                  ref={closeRef}
                  type="button"
                  onClick={() => setPreview(null)}
                  className="rounded-md border border-slate-700 bg-slate-800 px-4 py-2 text-sm text-slate-100 hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-400"
                >
                  {t("common.close")}
                </button>
              </header>
              <div className="min-h-0 flex-1 bg-slate-100 p-2 sm:p-3">
                {preview.url ? (
                  <iframe
                    title={t("preview.title")}
                    src={preview.url}
                    className="h-full w-full rounded border border-slate-200 bg-white"
                  />
                ) : (
                  <pre className="h-full w-full overflow-auto rounded border border-slate-200 bg-white p-4 font-mono text-xs text-slate-900">
                    {preview.text}
                  </pre>
                )}
              </div>
            </section>
          </div>,
          document.body,
        )}
    </div>
  );
}
