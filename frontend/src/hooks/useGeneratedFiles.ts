import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { readCsrfCookie } from "../lib/csrf";
import { triggerDownload } from "../lib/download";

export type GeneratedFile = {
  id: number;
  template_name: string;
  kind: "pdf" | "zpl";
  mode: "single" | "series" | "bill" | "stock" | "reprint";
  row_count: number | null;
  size_bytes: number;
  created_at: string;
  download_name: string;
};

const HISTORY_KEY = ["history"] as const;

export function useHistory() {
  return useQuery({
    queryKey: HISTORY_KEY,
    queryFn: () => api<{ files: GeneratedFile[] }>("/api/history").then((r) => r.files),
  });
}

export function useDeleteGeneratedFile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api(`/api/history/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: HISTORY_KEY });
    },
  });
}

/** Load an owner-scoped generated file for preview or download. */
export async function fetchHistoryFile(file: GeneratedFile): Promise<Blob> {
  const csrf = readCsrfCookie();
  const response = await fetch(`/api/history/${file.id}/download`, {
    credentials: "include",
    headers: csrf ? { "X-CSRF-Token": csrf } : undefined,
  });
  if (!response.ok) throw new Error(`download failed: ${response.status}`);
  return response.blob();
}

export async function downloadHistoryFile(file: GeneratedFile): Promise<void> {
  const blob = await fetchHistoryFile(file);
  triggerDownload(blob, file.download_name);
}
