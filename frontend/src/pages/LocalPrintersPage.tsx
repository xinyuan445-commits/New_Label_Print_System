import { useState } from "react";
import { Button } from "../components/ui/Button";
import { useLocalPrinters } from "../hooks/useLocalPrinters";
import {
  defaultLocalPrinter,
  readLocalPrinterSettings,
  saveLocalPrinterSettings,
  visibleLocalPrinters,
} from "../lib/localPrinterSettings";

export function LocalPrintersPage() {
  const [settings, setSettings] = useState(readLocalPrinterSettings);
  const [saveError, setSaveError] = useState(false);
  const printers = useLocalPrinters();
  const names = printers.data ?? [];
  const visible = visibleLocalPrinters(names, settings);
  const defaultPrinter = defaultLocalPrinter(names, settings);

  function updateSettings(next: typeof settings) {
    setSettings(next);
    setSaveError(!saveLocalPrinterSettings(next));
  }

  function toggleVisibility(name: string) {
    const hiddenPrinters = settings.hiddenPrinters.includes(name)
      ? settings.hiddenPrinters.filter((printer) => printer !== name)
      : [...settings.hiddenPrinters, name];
    const next = { ...settings, hiddenPrinters };
    next.defaultPrinter = defaultLocalPrinter(names, next) || null;
    updateSettings(next);
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold">本机打印机</h1>
        <div className="flex gap-3">
          <a className="btn btn-secondary" href="/api/print-assistant/windows">
            安装 / 更新打印助手
          </a>
          <Button
            variant="secondary"
            disabled={printers.isFetching}
            onClick={() => void printers.refetch()}
          >
            {printers.isFetching ? "读取中…" : "刷新"}
          </Button>
        </div>
      </header>

      {printers.isPending && <p className="text-sm text-slate-400">正在读取本机打印机…</p>}
      {printers.isError && (
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-300">
          <p>未连接本机打印助手</p>
          <p className="mt-2">下载后解压，双击 install.bat，再从桌面“标签打印系统”进入。</p>
        </div>
      )}
      {saveError && (
        <p role="alert" className="text-sm text-rose-400">
          无法保存打印机设置
        </p>
      )}
      {printers.isSuccess && (
        <>
          <p className="text-sm text-slate-400">
            共 {names.length} 台，显示 {visible.length} 台
          </p>
          {printers.data.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-700 p-6 text-center text-sm text-slate-400">
              这台电脑没有已安装的打印机
            </p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/40">
              <table className="w-full min-w-[480px] text-left text-sm">
                <thead className="bg-slate-900 text-slate-400">
                  <tr>
                    <th className="px-4 py-3">打印机</th>
                    <th className="px-4 py-3 text-center">默认</th>
                    <th className="px-4 py-3 text-center">显示</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {names.map((name) => {
                    const shown = visible.includes(name);
                    return (
                      <tr key={name}>
                        <td className="break-all px-4 py-3">{name}</td>
                        <td className="px-4 py-3 text-center">
                          <input
                            type="radio"
                            name="default-printer"
                            aria-label={`设 ${name} 为默认打印机`}
                            checked={shown && defaultPrinter === name}
                            disabled={!shown}
                            onChange={() => updateSettings({ ...settings, defaultPrinter: name })}
                          />
                        </td>
                        <td className="px-4 py-3 text-center">
                          <input
                            type="checkbox"
                            aria-label={`显示 ${name}`}
                            checked={shown}
                            onChange={() => toggleVisibility(name)}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
