const CASH_AMOUNT = /^\d{1,13}(?:\.\d{1,2})?$/;

function toMinorUnits(value: string): bigint | null {
  const normalized = value.trim();
  if (!CASH_AMOUNT.test(normalized)) return null;
  const [whole = "0", fraction = ""] = normalized.split(".");
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
}

function fromMinorUnits(value: bigint): string {
  const whole = (value / 100n).toString();
  const fraction = (value % 100n).toString().padStart(2, "0");
  return `${whole}.${fraction}`;
}

/** Returns exact change due, or null if the tender is invalid/short. */
export function retailCashChangeDue(total: string, cashReceived: string): string | null {
  const totalMinor = toMinorUnits(total);
  const receivedMinor = toMinorUnits(cashReceived);
  if (totalMinor === null || receivedMinor === null || receivedMinor < totalMinor) return null;
  return fromMinorUnits(receivedMinor - totalMinor);
}
