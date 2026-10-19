import { useQuery } from "@tanstack/react-query";
import { fetchLocalPrinters } from "../lib/localAgent";

async function readPrinters(): Promise<string[]> {
  const printers = await fetchLocalPrinters();
  return printers.filter((printer) => printer.kind === "local").map((printer) => printer.name);
}

export function useLocalPrinters(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["this-computer-printers"],
    queryFn: readPrinters,
    enabled: options?.enabled ?? true,
    retry: false,
    refetchInterval: 30_000,
  });
}
