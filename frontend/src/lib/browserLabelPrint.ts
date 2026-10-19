export const BROWSER_PRINTER = "浏览器打印";
export const BROWSER_PRINT_EVENT = "browser-label-print";
export type BrowserPrintDialog = {
  pdfUrl: string;
  count: number;
  resolve: (printed: boolean) => void;
};
let current: BrowserPrintDialog | null = null;
export function currentBrowserPrint() {
  return current;
}
export function confirmBrowserPrint(printed: boolean) {
  const request = current;
  current = null;
  window.dispatchEvent(new Event(BROWSER_PRINT_EVENT));
  request?.resolve(printed);
}
export function openBrowserPrint(pdfUrl: string, count: number): Promise<boolean> {
  if (current) throw new Error("已有打印窗口打开");
  return new Promise((resolve) => {
    current = { pdfUrl, count, resolve };
    window.dispatchEvent(new Event(BROWSER_PRINT_EVENT));
  });
}
