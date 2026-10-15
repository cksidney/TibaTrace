import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';
import type { HQOverview } from './api.js';
import { IntakeModal } from './IntakeModal.js';

const IngestionWorkspace = createContext<(action: () => void) => void>((action) => action());
export const useIngestionWorkspace = () => useContext(IngestionWorkspace);

/** A platform overview is a reading scope. Intake explicitly chooses one tenant. */
export function IngestionWorkspaceProvider({ tenantId, tenants, onSelectTenant, children }: {
  readonly tenantId: string;
  readonly tenants: HQOverview['network_items'];
  readonly onSelectTenant: (id: string) => Promise<void>;
  readonly children: ReactNode;
}) {
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [selection, setSelection] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const choices = tenants.filter((tenant) => tenant.status === 'ACTIVE');
  return <IngestionWorkspace.Provider value={(action) => {
    if (tenantId) { action(); return; }
    setSelection(''); setError(''); setPending(() => action);
  }}>
    {children}
    {pending && <IntakeModal title="Choose an intake workspace" busy={busy} onClose={() => setPending(null)}>
      <p>Choose the pharmacy that owns this new record. Its permissions and review requirements apply.</p>
      {choices.length ? <form onSubmit={(event) => {
        event.preventDefault();
        if (busy || !choices.some((tenant) => tenant.id === selection)) return;
        setBusy(true); setError('');
        void onSelectTenant(selection).then(() => {
          setPending(null); pending();
        }).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : 'The workspace could not be opened. Try again.'))
          .finally(() => setBusy(false));
      }}>
        <label className="business-field"><span>Operating tenant</span><select required disabled={busy} value={selection} onChange={(event) => setSelection(event.target.value)}>
          <option value="">Choose a pharmacy</option>{choices.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
        </select></label>
        {error && <p role="alert" className="business-dialog-error">{error}</p>}
        <footer><button className="secondary-button" type="button" disabled={busy} onClick={() => setPending(null)}>Cancel</button><button className="primary-button" type="submit" disabled={busy || !selection}>{busy ? 'Opening…' : 'Continue to form'}</button></footer>
      </form> : <><p role="status">No active pharmacy workspace is available. Register or activate a pharmacy in Network before entering tenant records.</p><footer><button className="secondary-button" type="button" onClick={() => setPending(null)}>Close</button></footer></>}
    </IntakeModal>}
  </IngestionWorkspace.Provider>;
}
