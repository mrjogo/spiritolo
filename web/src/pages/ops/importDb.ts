// Helpers behind /ops → Import: the staged-file shape, the status query key,
// and the digest-checked upload (kept out of the component file for fast refresh).
import { ApiError } from '../../api';

export interface StagedInfo {
  bytes: number;
  sha256: string;
  staged_at: string;
  migrations: string[];
  pending_migrations: string[];
  counts: Record<string, number>;
  operators_carried: number;
}

export interface ImportStatus {
  staged: StagedInfo | null;
  restart_on_apply: boolean;
}

export const importStatusKey = ['importDb'] as const;

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  // Hash through a view built in this realm: Node 20's WebCrypto (the test
  // runtime) rejects an ArrayBuffer created by jsdom's Blob as foreign.
  const digest = await crypto.subtle.digest('SHA-256', new Uint8Array(data));
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

export async function uploadDatabase(file: File): Promise<StagedInfo> {
  const bytes = await file.arrayBuffer();
  const sha = await sha256Hex(bytes);
  const res = await fetch('/api/ops/import-db', {
    method: 'POST',
    headers: { 'content-type': 'application/octet-stream', 'x-content-sha256': sha },
    body: bytes,
    credentials: 'same-origin',
  });
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail ?? detail;
    } catch {
      /* non-JSON */
    }
    throw new ApiError(res.status, detail);
  }
  return ((await res.json()) as { staged: StagedInfo }).staged;
}
