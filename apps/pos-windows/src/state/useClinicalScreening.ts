import {
  UnreadableScreeningResponse,
  permitsProgression,
  readScreeningResult,
} from '@dawatrace/shared/clinical/index.js';
import type { ScreeningResult } from '@dawatrace/shared/clinical/index.js';
import { resolveFetcher } from '@dawatrace/shared/auth/fetcher.js';
import { useCallback, useEffect, useState } from 'react';

import type { ClinicalSummary } from '../components/tibatrace/ClinicalRail.js';
import type { ClinicalFinding } from '../components/tibatrace/ClinicalRail.js';

/**
 * Fetches the clinical screening for the selected episode.
 *
 * Until this existed, `App.tsx` held `const [clinical] = useState(null)` -- a
 * state with no setter -- so the rail rendered "No clinical result" for every
 * episode forever and `evaluatePosClinicalScreening` had no call sites anywhere
 * in the repository. The drug-interaction engine was real and unreachable.
 *
 * Every path that is not an authoritative "safe" answer resolves to a summary
 * that does not permit progression. A request that failed, a response we could
 * not read, a screening still in flight and an episode nobody has screened are
 * all the same fact to a dispenser: nothing has checked this prescription.
 */

export interface ClinicalScreeningState {
  readonly summary: ClinicalSummary | null;
  readonly loading: boolean;
  /** Operator-facing reason the screening is unavailable. Empty when fine. */
  readonly error: string;
}

interface EpisodeLike {
  readonly id: string;
  readonly dispensing_number: string;
  readonly patient_id?: string;
  readonly prescription_id?: string;
  readonly lines?: readonly {
    readonly id: string;
    readonly sku_id?: string;
    readonly clinical_product_id?: string;
    readonly quantity_to_supply?: number;
  }[];
}

/** Nothing is known. Never presented as safe. */
const UNSCREENED: ClinicalSummary = {
  safeToProceed: false,
  screened: false,
  stale: false,
  blockingCount: 0,
  findings: [],
  connectivity: 'ONLINE',
};

function toFindings(result: ScreeningResult): ClinicalFinding[] {
  return result.findings.map((finding) => ({
    id: finding.id,
    severity:
      finding.severity === 'CRITICAL' || finding.severity === 'HIGH'
        ? 'BLOCKING'
        : finding.severity === 'MODERATE'
          ? 'PHARMACIST_REVIEW'
          : finding.severity === 'LOW'
            ? 'ACTION_REQUIRED'
            : 'INFORMATION',
    category: finding.category,
    title: finding.title,
    explanation: finding.explanation,
    recommendation: finding.recommendation,
    blocking: finding.blocking,
    overrideAllowed: finding.overrideAllowed,
    requiresPharmacist: finding.requiresPharmacist,
  }));
}

function toSummary(result: ScreeningResult): ClinicalSummary {
  return {
    // permitsProgression, not safeToProceed alone: a server that claims safe
    // while reporting a blocker is contradicting itself, and the restrictive
    // reading wins.
    safeToProceed: permitsProgression(result),
    screened: true,
    stale: false,
    blockingCount: result.blockingCount,
    findings: toFindings(result),
    connectivity: 'ONLINE',
    ...(result.evaluatedAt ? { evaluatedAt: result.evaluatedAt } : {}),
  };
}

export function useClinicalScreening(
  episode: EpisodeLike | null,
  options: {
    readonly deviceId?: string;
    readonly baseUrl?: string;
    readonly fetcher?: typeof fetch;
  } = {},
): ClinicalScreeningState & { readonly refresh: () => Promise<void> } {
  const [state, setState] = useState<ClinicalScreeningState>({
    summary: null,
    loading: false,
    error: '',
  });

  const deviceId = options.deviceId ?? 'POS-WINDOWS';
  const baseUrl = options.baseUrl ?? '';
  const fetcher = resolveFetcher(options.fetcher);

  const refresh = useCallback(async () => {
    if (!episode) {
      setState({ summary: null, loading: false, error: '' });
      return;
    }

    const lines = episode.lines ?? [];
    if (lines.length === 0) {
      setState({
        summary: UNSCREENED,
        loading: false,
        error: 'No dispensing lines are loaded, so nothing has been screened.',
      });
      return;
    }

    setState((previous) => ({ ...previous, loading: true, error: '' }));

    try {
      const response = await fetcher(`${baseUrl}/api/pos/clinical-screening/evaluate/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({
          // Stable per episode so a re-render reuses the screening instead of
          // creating a new one on every keystroke.
          transaction_id: `POS-WINDOWS-${episode.dispensing_number || episode.id}`,
          device_id: deviceId,
          patient_id: episode.patient_id ?? null,
          prescription_id: episode.prescription_id ?? null,
          dispensing_episode_id: episode.id,
          basket_lines: lines.map((line) => ({
            line_id: line.id,
            sku_id: line.sku_id ?? null,
            clinical_product_id: line.clinical_product_id ?? null,
            quantity: line.quantity_to_supply ?? 0,
          })),
        }),
      });

      if (!response.ok) {
        setState({
          summary: UNSCREENED,
          loading: false,
          error: `Clinical screening could not be performed (server responded ${response.status}). Supply is not authorised.`,
        });
        return;
      }

      setState({ summary: toSummary(readScreeningResult(await response.json())), loading: false, error: '' });
    } catch (error) {
      const unreadable = error instanceof UnreadableScreeningResponse;
      setState({
        summary: UNSCREENED,
        loading: false,
        error: unreadable
          ? 'The clinical screening response could not be read. Supply is not authorised.'
          : 'Clinical screening could not be reached. Supply is not authorised until screening completes.',
      });
    }
  }, [episode, deviceId, baseUrl, fetcher]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { ...state, refresh };
}
