import {
  PosOperationsClient,
  resolveOperationalContext,
} from '@dawatrace/shared/operational/index.js';
import type { PosOperationalContext } from '@dawatrace/shared/operational/index.js';
import { fontSize, spacing, statusPalette, surface, text } from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

interface OperationalStatusStripProps {
  readonly apiBaseUrl: string;
  readonly apiFetch: typeof fetch;
  readonly deviceId: string;
  readonly operatorId: string;
}

export function OperationalStatusStrip({
  apiBaseUrl,
  apiFetch,
  deviceId,
  operatorId,
}: OperationalStatusStripProps) {
  const client = useMemo(
    () => new PosOperationsClient(`${apiBaseUrl}/api/pos/shift`, { fetcher: apiFetch }),
    [apiBaseUrl, apiFetch],
  );
  const [context, setContext] = useState<PosOperationalContext | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    if (!deviceId || !operatorId) return;
    setRefreshing(true);
    try {
      const [registers, businessDays, openSessions, devices] = await Promise.all([
        client.getRegisters(),
        client.getBusinessDays(),
        client.getOpenSessions(),
        client.getDevices(),
      ]);
      setContext(
        resolveOperationalContext({
          deviceId,
          operatorId,
          registers,
          businessDays,
          openSessions,
          devices,
        }),
      );
      setError('');
    } catch (cause) {
      setContext(null);
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setRefreshing(false);
    }
  }, [client, deviceId, operatorId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const state = error || context?.readiness === 'UNASSIGNED'
    ? 'BLOCKING'
    : context?.readiness === 'READY'
      ? 'SAFE'
      : 'ACTION_REQUIRED';
  const palette = statusPalette[state];
  const title = error
    ? 'Operational status unavailable'
    : context?.readiness === 'READY'
      ? 'Register and accountable shift verified'
      : context?.readiness === 'UNASSIGNED'
        ? 'Register assignment required'
        : context
          ? 'Operational attention required'
          : 'Loading operational status';
  const detail = error || context?.notices[0] || 'Server-derived operational context is current.';

  return (
    <View accessibilityLiveRegion="polite" style={[styles.root, { backgroundColor: palette.surface, borderColor: palette.border }]}>
      <View style={styles.copy}>
        <Text style={[styles.title, { color: palette.foreground }]}>{title}</Text>
        <Text style={styles.detail}>{detail}</Text>
        <Text style={styles.context}>
          {context?.register?.branch_code ?? 'Branch unassigned'} · {context?.register?.code ?? 'Register unassigned'} · {context?.businessDay?.business_date ?? 'Business date unavailable'}
        </Text>
        <Text style={styles.context}>
          {context?.operatorShift ? `Shift ${context.operatorShift.state.replace(/_/g, ' ')}` : 'No active shift'} · {context?.deviceHealth ? `Printer ${context.deviceHealth.printer_paper_level}` : 'No printer report'}
        </Text>
      </View>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Refresh operational status"
        disabled={refreshing || !deviceId || !operatorId}
        onPress={() => void refresh()}
        style={[styles.refresh, { borderColor: palette.border }]}
      >
        <Text style={[styles.refreshLabel, { color: palette.foreground }]}>{refreshing ? '…' : 'Refresh'}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flexDirection: 'row', gap: spacing.sm, paddingHorizontal: spacing.lg, paddingVertical: spacing.sm, borderBottomWidth: 1, alignItems: 'center' },
  copy: { flex: 1, gap: 2 },
  title: { fontSize: 13, fontWeight: '700' },
  detail: { color: text.secondary, fontSize: fontSize.meta },
  context: { color: text.secondary, fontSize: fontSize.meta },
  refresh: { minWidth: 68, minHeight: 40, paddingHorizontal: spacing.sm, borderWidth: 1, borderRadius: 8, justifyContent: 'center', alignItems: 'center', backgroundColor: surface.raised },
  refreshLabel: { fontSize: fontSize.caption, fontWeight: '700' },
});
