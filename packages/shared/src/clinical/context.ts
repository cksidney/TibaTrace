/**
 * TibaTrace POS Clinical Screening — Context Hash Generator
 *
 * Generates deterministic SHA-256 context hashes for clinical screening.
 * Used to detect basket changes and avoid duplicate evaluations.
 *
 * This module is platform-neutral and works in both browser and Node.js environments.
 */

import type { PosClinicalBasketLine } from "./types.js";

/**
 * Data structure used to build the context hash.
 * Only clinically relevant fields are included.
 */
interface ClinicalContextHashInput {
  basketLines: PosClinicalBasketLine[];
  patientId?: string;
  prescriptionId?: string;
  allergyCodes?: string[];
  pregnancyStatus?: string;
  lactationStatus?: string;
  renalImpairment?: boolean;
  hepaticImpairment?: boolean;
  ageYears?: number;
  weightKg?: number;
}

/**
 * Build a deterministic clinical context hash from basket and patient data.
 *
 * The hash is computed from a canonical JSON representation of:
 * - Sorted basket lines (by lineId) with clinically relevant fields only
 * - Patient identifier
 * - Prescription identifier
 * - Sorted allergy codes
 * - Patient clinical summary fields
 *
 * This ensures:
 * - Same basket + same patient context = same hash (no duplicate screening)
 * - Any change to medicines, quantities, or patient data = different hash (re-screening required)
 * - Field ordering does not affect the hash (deterministic)
 */
export async function buildClinicalContextHash(
  input: ClinicalContextHashInput
): Promise<string> {
  const canonical = buildCanonicalRepresentation(input);
  return computeSha256(canonical);
}

/**
 * Synchronous version for environments without async crypto.
 * Uses a simple hash function instead of Web Crypto API.
 */
export function buildClinicalContextHashSync(
  input: ClinicalContextHashInput
): string {
  const canonical = buildCanonicalRepresentation(input);
  return simpleHash(canonical);
}

/**
 * Build a canonical JSON string from the context input.
 * All arrays are sorted, all fields are ordered consistently.
 */
function buildCanonicalRepresentation(
  input: ClinicalContextHashInput
): string {
  const sortedLines = [...input.basketLines]
    .sort((a, b) => a.lineId.localeCompare(b.lineId))
    .map((line) => ({
      lineId: line.lineId,
      skuId: line.commercialSkuId ?? "",
      clinicalProductId: line.clinicalMedicinalProductId ?? "",
      ingredientIds: [...(line.activeIngredientIds ?? [])].sort(),
      quantity: line.quantity,
      doseValue: line.doseValue ?? null,
      doseUnit: line.doseUnit ?? "",
      frequencyPerDay: line.frequencyPerDay ?? null,
      durationDays: line.durationDays ?? null,
      isControlled: line.isControlled ?? false,
      isPrescriptionOnly: line.isPrescriptionOnly ?? false,
    }));

  const hashInput = {
    lines: sortedLines,
    patientId: input.patientId ?? "",
    prescriptionId: input.prescriptionId ?? "",
    allergyCodes: [...(input.allergyCodes ?? [])].sort(),
    pregnancyStatus: input.pregnancyStatus ?? "",
    lactationStatus: input.lactationStatus ?? "",
    renalImpairment: input.renalImpairment ?? false,
    hepaticImpairment: input.hepaticImpairment ?? false,
    ageYears: input.ageYears ?? null,
    weightKg: input.weightKg ?? null,
  };

  return JSON.stringify(hashInput);
}

/**
 * Compute SHA-256 hash using the Web Crypto API.
 * Available in modern browsers and Node.js 15+.
 */
async function computeSha256(data: string): Promise<string> {
  const encoder = new TextEncoder();
  const dataBuffer = encoder.encode(data);

  if (typeof globalThis.crypto !== "undefined" && globalThis.crypto.subtle) {
    const hashBuffer = await globalThis.crypto.subtle.digest(
      "SHA-256",
      dataBuffer
    );
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  // Fallback to simple hash
  return simpleHash(data);
}

/**
 * Simple deterministic hash for environments without Web Crypto.
 * Uses FNV-1a variant producing a 64-char hex string.
 * This is NOT cryptographic — used only for deduplication, not security.
 */
function simpleHash(data: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;

  for (let i = 0; i < data.length; i++) {
    const ch = data.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }

  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
  h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
  h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);

  const part1 = (h1 >>> 0).toString(16).padStart(8, "0");
  const part2 = (h2 >>> 0).toString(16).padStart(8, "0");

  // Repeat to fill 64 chars for consistency with SHA-256 length
  return (part1 + part2).repeat(4);
}
