/**
 * Fixed two-place decimal formatting without binary floats.
 *
 * Money and terminal quantities travel as decimal strings. Passing them through
 * `Number(...).toFixed(2)` is how a drawer that balanced in the database stops
 * balancing on screen.
 */

const TWO_PLACE = /^-?\d+(\.\d+)?$/;

function splitSigned(text: string): { negative: boolean; whole: string; fraction: string } {
  const negative = text.startsWith("-");
  const raw = negative ? text.slice(1) : text;
  const [whole = "0", fraction = ""] = raw.split(".");
  return { negative, whole: whole.replace(/^0+(?=\d)/, "") || "0", fraction };
}

/** Round half-up a non-negative decimal string to `places` fraction digits. */
function roundHalfUp(whole: string, fraction: string, places: number): { whole: string; fraction: string } {
  const padded = (fraction + "0".repeat(places + 1)).slice(0, places + 1);
  const keep = padded.slice(0, places);
  const next = padded.slice(places, places + 1);
  if (next >= "5") {
    const digits = (whole + keep).split("").map((d) => Number(d));
    let i = digits.length - 1;
    digits[i] = (digits[i] ?? 0) + 1;
    while (i > 0 && digits[i] === 10) {
      digits[i] = 0;
      i -= 1;
      digits[i] = (digits[i] ?? 0) + 1;
    }
    if (digits[0] === 10) {
      digits[0] = 0;
      digits.unshift(1);
    }
    const joined = digits.join("");
    const cut = joined.length - places;
    return {
      whole: joined.slice(0, cut) || "0",
      fraction: places ? joined.slice(cut) : "",
    };
  }
  return { whole, fraction: keep.padEnd(places, "0") };
}

export function formatDecimal(
  value: string | number | null | undefined,
  places = 2,
): string {
  if (value === null || value === undefined) return "";
  const text = String(value).trim();
  if (text === "" || !TWO_PLACE.test(text)) return "";
  const { negative, whole, fraction } = splitSigned(text);
  const rounded = roundHalfUp(whole, fraction, places);
  const body = places > 0 ? `${rounded.whole}.${rounded.fraction}` : rounded.whole;
  return `${negative ? "-" : ""}${body}`;
}

export function formatMoney(
  value: string | number | null | undefined,
  currency = "KES",
): string {
  const amount = formatDecimal(value, 2);
  if (!amount) return "—";
  const negative = amount.startsWith("-");
  const unsigned = negative ? amount.slice(1) : amount;
  const [whole = "0", fraction = "00"] = unsigned.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${currency} ${negative ? "-" : ""}${grouped}.${fraction}`;
}
