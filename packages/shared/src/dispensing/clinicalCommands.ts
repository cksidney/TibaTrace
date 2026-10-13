import type { AuthorizedDispensingItem } from './types.js';

/** A rejected command and an unknown network outcome are deliberately distinct. */
export async function clinicalCommand(
  apiFetch: typeof fetch, episodeId: string, command: string, body: unknown,
): Promise<unknown> {
  let response: Response;
  try {
    response = await apiFetch(`/api/pos/dispensing/episodes/${encodeURIComponent(episodeId)}/${command}/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error('Outcome unknown. Refresh the episode before retrying; retain the same reservation key.');
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = typeof payload === 'string' ? payload : JSON.stringify(payload);
    throw new Error(message || `The ${command} command was refused (${response.status}).`);
  }
  return payload;
}

export function reservationQuantityValid(item: AuthorizedDispensingItem, quantity: string): boolean {
  const amount = Number(quantity);
  return Number.isFinite(amount) && amount > 0 && amount <= Number(item.quantity_remaining)
    && Number(item.reserved_quantity) === 0;
}
