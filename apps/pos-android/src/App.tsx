import {
  permitsProgression,
  readScreeningResult,
} from '@dawatrace/shared/clinical/index.js';
import {
  actionIdempotencyKey,
  DispensingWorkflow,
  DurableActionJournal,
  PosDispensingClient,
} from '@dawatrace/shared/dispensing/index.js';
import type {
  CounsellingRecordRequest,
  DispensingEpisodeDTO,
  GateState,
  PaymentTenderType,
  JournalAction,
} from '@dawatrace/shared/dispensing/index.js';
import {
  fontSize,
  spacing,
  statusPalette,
  surface,
  text,
} from '@dawatrace/shared/design-system/index.js';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StatusBar,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import type { AndroidClinicalSummary } from './components/tibatrace/ClinicalSummaryCard';
import { OperationalStatusStrip } from './components/tibatrace/OperationalStatusStrip';
import { TibaTraceBrand } from './components/tibatrace/TibaTraceBrand';
import { createAndroidPosRuntime } from './native/runtime';
import { SecureOfflineStore } from './offline/secureStore';
import { CollectionScreen, CounsellingScreen } from './screens/CounsellingScreen';
import { DispensingScreen } from './screens/DispensingScreen';
import { PaymentScreen } from './screens/PaymentScreen';
import { RetailScreen } from './screens/RetailScreen';

type WorkspaceScreen = 'queue' | 'episode' | 'payment' | 'counselling' | 'collection' | 'retail';

const runtime = createAndroidPosRuntime();
const EMPTY_GATE: GateState = {
  canTakePayment: false,
  canConfirmCollection: false,
  blockedReason: 'No dispensing episode loaded.',
  outcomeUnknown: false,
};
const UNSCREENED: AndroidClinicalSummary = {
  safeToProceed: false,
  screened: false,
  stale: false,
  blockingCount: 0,
  connectivity: 'ONLINE',
  headlineTitle: 'Clinical screening required',
  headlineDetail: 'Medicine cannot progress until an authoritative screening completes.',
  headlineStatus: 'PROCESSING',
};

export default function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    void (async () => {
      try {
        if (!(await runtime.secureStore.isAvailable())) {
          throw new Error('Android Keystore is unavailable. This device cannot run TibaTrace POS.');
        }
        const restored = await runtime.session.restore();
        if (restored) {
          const response = await runtime.session.fetch('/api/identity/me/');
          if (!response.ok) throw new Error('The saved operator session is no longer valid.');
          setAuthenticated(true);
        }
      } catch (cause) {
        await runtime.session.logout().catch(() => undefined);
        setError(cause instanceof Error ? cause.message : String(cause));
      } finally {
        setRestoring(false);
      }
    })();
  }, []);

  if (restoring) {
    return <LoadingScreen message="Restoring secure operator session…" />;
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar barStyle="dark-content" backgroundColor={surface.page} />
      {authenticated ? (
        <PosWorkspace
          onLogout={async () => {
            await runtime.session.logout();
            setAuthenticated(false);
          }}
        />
      ) : (
        <LoginScreen
          initialError={error}
          onLogin={async (username, password) => {
            await runtime.session.login(username, password);
            setError('');
            setAuthenticated(true);
          }}
        />
      )}
    </SafeAreaView>
  );
}

function PosWorkspace({ onLogout }: { readonly onLogout: () => Promise<void> }) {
  const client = useMemo(
    () =>
      new PosDispensingClient(
        `${runtime.apiBaseUrl}/api/pos/dispensing`,
        '',
        15000,
        { fetcher: runtime.session.fetch.bind(runtime.session) },
      ),
    [],
  );
  const workflow = useMemo(() => new DispensingWorkflow(client), [client]);
  const [queue, setQueue] = useState<readonly DispensingEpisodeDTO[]>([]);
  const [episode, setEpisode] = useState<DispensingEpisodeDTO | null>(null);
  const [gate, setGate] = useState<GateState>(EMPTY_GATE);
  const [clinical, setClinical] = useState<AndroidClinicalSummary>(UNSCREENED);
  const [screen, setScreen] = useState<WorkspaceScreen>('queue');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const [deviceId, setDeviceId] = useState('');
  const [journal, setJournal] = useState<DurableActionJournal | null>(null);
  const [journalReady, setJournalReady] = useState(false);
  const [journalBlocked, setJournalBlocked] = useState(false);

  const syncWorkflow = useCallback(() => {
    setEpisode(workflow.current);
    setGate(workflow.gate());
  }, [workflow]);

  const loadQueue = useCallback(async () => {
    setBusy(true);
    try {
      setQueue(await client.getQueue());
      setNotice('');
    } catch (cause) {
      setNotice(describe(cause));
    } finally {
      setBusy(false);
    }
  }, [client]);

  useEffect(() => {
    void runtime
      .deviceId()
      .then(async (resolvedDeviceId) => {
        setDeviceId(resolvedDeviceId);
        const tenantId = runtime.session.current?.tenantId;
        if (!tenantId) throw new Error('The operator session has no tenant.');
        const next = new DurableActionJournal(
          new SecureOfflineStore({
            keystore: runtime.secureStore,
            tenantId,
            deviceId: resolvedDeviceId,
          }),
        );
        await next.initialise();
        setJournal(next);
        setJournalReady(true);
        if (workflow.current) {
          setJournalBlocked(!next.canProceed(workflow.current.id));
        }
      })
      .catch((cause: unknown) => setNotice(describe(cause)));
    void loadQueue();
  }, [loadQueue]);

  const selectEpisode = useCallback(
    async (id: string) => {
      setBusy(true);
      setClinical(UNSCREENED);
      try {
        const loaded = await workflow.load(id);
        syncWorkflow();
        setJournalBlocked(journal ? !journal.canProceed(loaded.id) : false);
        setScreen('episode');
        setNotice('');
        setClinical(await screenClinically(loaded, deviceId || (await runtime.deviceId())));
      } catch (cause) {
        setClinical({
          ...UNSCREENED,
          headlineTitle: 'Clinical screening unavailable',
          headlineDetail: 'Supply is blocked until the screening service can be reached.',
          headlineStatus: 'BLOCKING',
        });
        setNotice(describe(cause));
      } finally {
        syncWorkflow();
        setBusy(false);
      }
    },
    [deviceId, journal, syncWorkflow, workflow],
  );

  const runAction = useCallback(
    async (action: () => Promise<{ readonly kind: string; readonly message?: string }>) => {
      setBusy(true);
      try {
        const outcome = await action();
        if (outcome.kind !== 'ok') setNotice(outcome.message ?? 'The action was not completed.');
        else setNotice('');
      } catch (cause) {
        setNotice(describe(cause));
      } finally {
        syncWorkflow();
        setBusy(false);
      }
    },
    [syncWorkflow],
  );

  const attempt = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const effectiveGate: GateState =
    !journalReady || journalBlocked
      ? {
          canTakePayment: false,
          canConfirmCollection: false,
          blockedReason: !journalReady
            ? 'Secure action recovery is still starting.'
            : 'A previous payment or collection has an unknown outcome. Reconcile it before continuing.',
          outcomeUnknown: journalBlocked,
        }
      : gate;

  const runJournalled = (
    input: JournalAction,
    action: () => Promise<{
      readonly kind: 'ok' | 'blocked' | 'unknown';
      readonly message?: string;
    }>,
  ) =>
    runAction(async () => {
      if (!journal) throw new Error('Secure action recovery is not ready.');
      try {
        return await journal.run(input, action);
      } finally {
        setJournalBlocked(!journal.canProceed(input.episodeId));
      }
    });

  return (
    <View style={styles.workspace}>
      <View style={styles.topBar}>
        <TibaTraceBrand />
        <Pressable accessibilityRole="button" onPress={() => setScreen('retail')} style={styles.secondary}>
          <Text style={styles.secondaryLabel}>Retail</Text>
        </Pressable>
        <Pressable accessibilityRole="button" onPress={() => void onLogout()} style={styles.secondary}>
          <Text style={styles.secondaryLabel}>Sign out</Text>
        </Pressable>
      </View>
      <OperationalStatusStrip
        apiBaseUrl={runtime.apiBaseUrl}
        apiFetch={runtime.session.fetch.bind(runtime.session) as typeof fetch}
        deviceId={deviceId}
      />
      {notice ? (
        <View accessibilityLiveRegion="assertive" style={styles.notice}>
          <Text style={styles.noticeText}>{notice}</Text>
        </View>
      ) : null}
      {busy ? <ActivityIndicator style={styles.progress} color="#12854A" /> : null}

      <View style={styles.screenArea}>
        {screen === 'queue' ? (
          <QueueScreen queue={queue} busy={busy} onRefresh={loadQueue} onSelect={selectEpisode} />
        ) : null}
        {screen === 'episode' ? (
          <DispensingScreen
            episode={episode}
            clinical={clinical}
            gateBlockedReason={effectiveGate.blockedReason}
            canConfirmCollection={effectiveGate.canConfirmCollection}
            onConfirmCollection={() => setScreen('collection')}
          />
        ) : null}
        {screen === 'payment' && episode ? (
          <PaymentScreen
          key={`${episode.id}-${episode.payment_state}`}
          paymentState={episode.payment_state}
          amountDue={episode.amount_due}
          amountSettled={episode.amount_settled}
          canTakePayment={effectiveGate.canTakePayment}
          blockedReason={effectiveGate.canTakePayment ? '' : effectiveGate.blockedReason}
          busy={busy}
          onTakePayment={(tender: PaymentTenderType, amount: string, reference: string) => {
            const idempotencyKey = actionIdempotencyKey(
              episode.id,
              'payment',
              attempt(),
            );
            const request = {
                tender_type: tender,
                paid_amount: amount,
                payment_reference: reference,
                device_id: deviceId,
                idempotency_key: idempotencyKey,
              };
            void runJournalled(
              {
                id: attempt(),
                type: 'PAYMENT',
                episodeId: episode.id,
                idempotencyKey,
                payload: request,
              },
              () => workflow.takePayment(request),
            );
          }}
          />
        ) : null}
        {screen === 'counselling' && episode ? (
          <CounsellingScreen
          key={`${episode.id}-${episode.counselling_status}`}
          counsellingStatus={episode.counselling_status}
          busy={busy}
          onRecord={(request: CounsellingRecordRequest) =>
            void runAction(() => workflow.recordCounselling(request))
          }
          />
        ) : null}
        {screen === 'collection' && episode ? (
          <CollectionScreen
          key={`${episode.id}-${episode.collected_at ?? ''}`}
          canConfirm={effectiveGate.canConfirmCollection}
          blockedReason={
            effectiveGate.canConfirmCollection ? '' : effectiveGate.blockedReason
          }
          collectedAt={episode.collected_at ?? null}
          collectorName={episode.collector_name}
          busy={busy}
          onConfirm={(name, idNumber, relationship) => {
            const idempotencyKey = actionIdempotencyKey(
              episode.id,
              'collection',
              attempt(),
            );
            const request = {
                collector_name: name,
                collector_id_number: idNumber,
                collector_relationship: relationship,
                idempotency_key: idempotencyKey,
              };
            void runJournalled(
              {
                id: attempt(),
                type: 'COLLECTION',
                episodeId: episode.id,
                idempotencyKey,
                payload: request,
              },
              () => workflow.confirmCollection(request),
            );
          }}
          />
        ) : null}
        {screen === 'retail' ? (
          <RetailScreen
            apiBaseUrl={runtime.apiBaseUrl}
            apiFetch={runtime.session.fetch.bind(runtime.session) as typeof fetch}
            deviceId={deviceId}
          />
        ) : null}
      </View>

      {screen !== 'queue' ? (
        <View style={styles.navigation}>
          <NavButton label="Queue" onPress={() => setScreen('queue')} />
          <NavButton label="Episode" onPress={() => setScreen('episode')} />
          <NavButton
            label="Payment"
            disabled={
              !effectiveGate.canTakePayment &&
              episode?.payment_state !== 'PARTIALLY_PAID'
            }
            onPress={() => setScreen('payment')}
          />
          <NavButton label="Counselling" onPress={() => setScreen('counselling')} />
          <NavButton label="Collection" onPress={() => setScreen('collection')} />
          <NavButton label="Retail" onPress={() => setScreen('retail')} />
        </View>
      ) : null}
    </View>
  );
}

function QueueScreen({
  queue,
  busy,
  onRefresh,
  onSelect,
}: {
  readonly queue: readonly DispensingEpisodeDTO[];
  readonly busy: boolean;
  readonly onRefresh: () => Promise<void>;
  readonly onSelect: (id: string) => Promise<void>;
}) {
  return (
    <ScrollView style={styles.screenArea} contentContainerStyle={styles.queue}>
      <View style={styles.queueHeader}>
        <View>
          <Text style={styles.title}>Dispensing queue</Text>
          <Text style={styles.muted}>{queue.length} prescriptions waiting</Text>
        </View>
        <Pressable disabled={busy} onPress={() => void onRefresh()} style={styles.secondary}>
          <Text style={styles.secondaryLabel}>Refresh</Text>
        </Pressable>
      </View>
      {queue.map((item) => (
        <Pressable
          key={item.id}
          accessibilityRole="button"
          onPress={() => void onSelect(item.id)}
          style={styles.queueItem}
        >
          <View>
            <Text style={styles.queueNumber}>{item.dispensing_number}</Text>
            {/* The resolved name, not `patient`, which is the row's UUID.
                This list is how an operator picks the right episode. */}
            <Text style={styles.muted}>
              {item.patient_name ?? 'Name not recorded'}
              {item.patient_number ? ` · ${item.patient_number}` : ''}
            </Text>
          </View>
          <Text style={styles.queueStatus}>{item.status.replace(/_/g, ' ')}</Text>
        </Pressable>
      ))}
      {!busy && queue.length === 0 ? (
        <Text style={styles.emptyText}>No prescriptions are currently waiting.</Text>
      ) : null}
    </ScrollView>
  );
}

function NavButton({
  label,
  disabled = false,
  onPress,
}: {
  readonly label: string;
  readonly disabled?: boolean;
  readonly onPress: () => void;
}) {
  return (
    <Pressable disabled={disabled} onPress={onPress} style={styles.navButton}>
      <Text style={[styles.navLabel, disabled && styles.navDisabled]}>{label}</Text>
    </Pressable>
  );
}

function LoginScreen({
  initialError,
  onLogin,
}: {
  readonly initialError: string;
  readonly onLogin: (username: string, password: string) => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(initialError);

  return (
    <ScrollView contentContainerStyle={styles.login}>
      <TibaTraceBrand />
      <Text style={styles.title}>Android POS</Text>
      <Text style={styles.muted}>Sign in with your assigned TibaTrace operator account.</Text>
      {error ? (
        <View style={styles.notice}>
          <Text style={styles.noticeText}>{error}</Text>
        </View>
      ) : null}
      <Text style={styles.label}>Username</Text>
      <TextInput
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="username"
        value={username}
        onChangeText={setUsername}
        style={styles.input}
      />
      <Text style={styles.label}>Password</Text>
      <TextInput
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="current-password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
        style={styles.input}
      />
      <Pressable
        disabled={busy || !username.trim() || !password}
        onPress={() => {
          setBusy(true);
          setError('');
          void onLogin(username.trim(), password)
            .catch((cause: unknown) => setError(describe(cause)))
            .finally(() => setBusy(false));
        }}
        style={[styles.primary, (busy || !username.trim() || !password) && styles.primaryDisabled]}
      >
        <Text style={styles.primaryLabel}>{busy ? 'Signing in…' : 'Sign in'}</Text>
      </Pressable>
      <Text style={styles.version}>Version {runtime.version}</Text>
    </ScrollView>
  );
}

function LoadingScreen({ message }: { readonly message: string }) {
  return (
    <SafeAreaView style={styles.loading}>
      <TibaTraceBrand />
      <ActivityIndicator color="#12854A" />
      <Text style={styles.muted}>{message}</Text>
    </SafeAreaView>
  );
}

async function screenClinically(
  episode: DispensingEpisodeDTO,
  deviceId: string,
): Promise<AndroidClinicalSummary> {
  const response = await runtime.session.fetch('/api/pos/clinical-screening/evaluate/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      transaction_id: `POS-ANDROID-${episode.dispensing_number}`,
      device_id: deviceId,
      prescription_id: episode.prescription,
      dispensing_episode_id: episode.id,
      basket_lines: episode.lines.map((line) => ({
        line_id: line.id,
        sku_id: line.supplied_sku || line.prescribed_sku,
        quantity: Number(line.quantity_authorized),
      })),
    }),
  });
  if (!response.ok) throw new Error(`Clinical screening responded ${response.status}.`);
  const result = readScreeningResult(await response.json());
  const safe = permitsProgression(result);
  return {
    safeToProceed: safe,
    screened: true,
    stale: false,
    blockingCount: result.blockingCount,
    connectivity: 'ONLINE',
    headlineTitle: safe
      ? 'Safe to proceed'
      : result.blockingCount > 0
        ? `${result.blockingCount} blocking finding${result.blockingCount === 1 ? '' : 's'}`
        : 'Clinical review required',
    headlineDetail: safe
      ? 'Clinical screening is current with no unresolved blocking findings.'
      : 'Review and resolve the clinical result before continuing.',
    headlineStatus: safe ? 'SAFE' : result.blockingCount > 0 ? 'BLOCKING' : 'PHARMACIST_REVIEW',
  };
}

function describe(cause: unknown): string {
  return cause instanceof Error ? cause.message : String(cause);
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: surface.page },
  workspace: { flex: 1, backgroundColor: surface.page },
  screenArea: { flex: 1 },
  topBar: {
    minHeight: 64,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderBottomWidth: 1,
    borderBottomColor: surface.border,
    backgroundColor: surface.raised,
  },
  progress: { position: 'absolute', zIndex: 10, top: 70, right: spacing.lg },
  notice: {
    margin: spacing.md,
    padding: spacing.md,
    borderRadius: 8,
    borderLeftWidth: 4,
    borderLeftColor: statusPalette.BLOCKING.accent,
    backgroundColor: statusPalette.BLOCKING.surface,
  },
  noticeText: { color: statusPalette.BLOCKING.foreground, fontSize: fontSize.body },
  queue: { padding: spacing.lg, gap: spacing.md, paddingBottom: spacing.xxxl },
  queueHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  title: { fontSize: fontSize.screenTitle, fontWeight: '700', color: text.primary },
  muted: { color: text.secondary, fontSize: fontSize.body },
  queueItem: {
    minHeight: 72,
    padding: spacing.md,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: surface.border,
    backgroundColor: surface.raised,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  queueNumber: { fontSize: fontSize.bodyLarge, fontWeight: '700', color: text.primary },
  queueStatus: { fontSize: fontSize.caption, color: text.secondary },
  emptyText: { paddingVertical: spacing.xxl, textAlign: 'center', color: text.secondary },
  navigation: {
    minHeight: 58,
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: surface.border,
    backgroundColor: surface.raised,
  },
  navButton: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xs },
  navLabel: { color: '#075E37', fontSize: fontSize.caption, fontWeight: '600' },
  navDisabled: { color: text.tertiary },
  login: { flexGrow: 1, justifyContent: 'center', padding: spacing.xl, gap: spacing.md },
  label: { color: text.secondary, fontSize: fontSize.caption, textTransform: 'uppercase' },
  input: {
    minHeight: 48,
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 10,
    backgroundColor: surface.raised,
    color: text.primary,
    fontSize: fontSize.bodyLarge,
  },
  primary: {
    minHeight: 52,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 10,
    backgroundColor: '#12854A',
    marginTop: spacing.md,
  },
  primaryDisabled: { backgroundColor: surface.sunken },
  primaryLabel: { color: '#fff', fontSize: fontSize.bodyLarge, fontWeight: '700' },
  secondary: {
    minHeight: 40,
    justifyContent: 'center',
    paddingHorizontal: spacing.md,
    borderWidth: 1,
    borderColor: surface.borderStrong,
    borderRadius: 8,
  },
  secondaryLabel: { color: text.primary, fontSize: fontSize.caption, fontWeight: '600' },
  loading: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: spacing.md },
  version: { marginTop: spacing.lg, color: text.tertiary, textAlign: 'center' },
});
