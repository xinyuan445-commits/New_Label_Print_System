export type LocalPrinterSettings = {
  defaultPrinter: string | null;
  hiddenPrinters: string[];
};

const STORAGE_KEY = "barcodelabelgen.local-printers.v1";

export function readLocalPrinterSettings(): LocalPrinterSettings {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (saved && typeof saved === "object") {
      const value = saved as Record<string, unknown>;
      return {
        defaultPrinter: typeof value.defaultPrinter === "string" ? value.defaultPrinter : null,
        hiddenPrinters: Array.isArray(value.hiddenPrinters)
          ? value.hiddenPrinters.filter((name): name is string => typeof name === "string")
          : [],
      };
    }
  } catch {
    // The page still works if browser storage is unavailable or malformed.
  }
  return { defaultPrinter: null, hiddenPrinters: [] };
}

export function saveLocalPrinterSettings(settings: LocalPrinterSettings): boolean {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    return true;
  } catch {
    return false;
  }
}

export function visibleLocalPrinters(names: string[], settings: LocalPrinterSettings): string[] {
  const hidden = new Set(settings.hiddenPrinters);
  return names.filter((name) => !hidden.has(name));
}

export function defaultLocalPrinter(names: string[], settings: LocalPrinterSettings): string {
  const visible = visibleLocalPrinters(names, settings);
  return visible.includes(settings.defaultPrinter ?? "")
    ? (settings.defaultPrinter ?? "")
    : (visible[0] ?? "");
}
