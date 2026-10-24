// Types + helpers for /ops → Operators, kept out of the component file so
// react-refresh stays happy.

export interface OperatorRow {
  id: number;
  handle: string;
  display_name: string;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
  passkeys: number;
  pending_invites: number;
}

export interface InviteResult {
  token: string;
  path: string;
  expires_at: string;
  operator_id: number;
}

export interface PasskeyRow {
  credential_id: string;
  label: string | null;
  transports: string[];
  created_at: string;
  last_used_at: string | null;
}

export const operatorsKey = ['ops', 'operators'] as const;
export const myPasskeysKey = ['auth', 'passkeys'] as const;

export function inviteUrl(path: string, origin: string = window.location.origin): string {
  return `${origin}${path}`;
}
