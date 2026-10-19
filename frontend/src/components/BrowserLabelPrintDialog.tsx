import { useEffect, useRef, useState } from "react";
import {
  BROWSER_PRINT_EVENT,
  confirmBrowserPrint,
  currentBrowserPrint,
} from "../lib/browserLabelPrint";
import { Button } from "./ui/Button";
import { Modal } from "./ui/Modal";

export function BrowserLabelPrintDialog() {
  const [request, setRequest] = useState(currentBrowserPrint);
  const [confirmed, setConfirmed] = useState(false);
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    const refresh = () => {
      setRequest(currentBrowserPrint());
      setConfirmed(false);
    };
    window.addEventListener(BROWSER_PRINT_EVENT, refresh);
    return () => window.removeEventListener(BROWSER_PRINT_EVENT, refresh);
  }, []);
  return (
    <Modal
      open={request !== null}
      onClose={() => confirmBrowserPrint(false)}
      title={`打印标签 · ${request?.count ?? 0} 张`}
      wide
    >
      {request && (
        <>
          <iframe
            ref={frame}
            title="打印标签"
            src={request.pdfUrl}
            className="h-[65vh] w-full rounded border border-slate-700"
          />
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <div className="text-sm">
              <p>在预览工具栏点打印，完成后再确认。</p>
              <label className="mt-2 flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                />
                我已确认标签打印完成
              </label>
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => confirmBrowserPrint(false)}>
                取消
              </Button>
              <Button disabled={!confirmed} onClick={() => confirmBrowserPrint(true)}>
                确认已打印
              </Button>
            </div>
          </div>
        </>
      )}
    </Modal>
  );
}
