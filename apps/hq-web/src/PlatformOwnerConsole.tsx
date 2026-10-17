import { useState } from 'react';

import { EtimsWorkspaceTab } from './EtimsWorkspaceTab.js';
import { Icon } from './icons.js';
import { IntegrationWorkspace } from './IntegrationWorkspace.js';
import { PosActivationWorkspace } from './PosActivationWorkspace.js';

interface PlatformOwnerConsoleProps {
  csrfToken: string;
  initialTab?: 'pos_activations' | 'integrations' | 'etims';
}

export function PlatformOwnerConsole({ csrfToken, initialTab = 'pos_activations' }: PlatformOwnerConsoleProps) {
  const [activeTab, setActiveTab] = useState<'pos_activations' | 'integrations' | 'etims'>(initialTab);

  return (
    <div className="platform-owner-console">
      {/* Console Tab Switcher */}
      <div className="platform-owner-nav-strip">
        <div className="platform-owner-tabs" role="tablist" aria-label="Platform Governance Workspaces">
          <button
            aria-selected={activeTab === 'pos_activations'}
            className={activeTab === 'pos_activations' ? 'platform-owner-tab is-active' : 'platform-owner-tab'}
            onClick={() => setActiveTab('pos_activations')}
            role="tab"
            type="button"
          >
            <Icon name="store" />
            <span>POS Terminal Activations</span>
          </button>
          <button
            aria-selected={activeTab === 'integrations'}
            className={activeTab === 'integrations' ? 'platform-owner-tab is-active' : 'platform-owner-tab'}
            onClick={() => setActiveTab('integrations')}
            role="tab"
            type="button"
          >
            <Icon name="network" />
            <span>National Integrations (DHA & PPB)</span>
          </button>
          <button
            aria-selected={activeTab === 'etims'}
            className={activeTab === 'etims' ? 'platform-owner-tab is-active' : 'platform-owner-tab'}
            onClick={() => setActiveTab('etims')}
            role="tab"
            type="button"
          >
            <Icon name="shield" />
            <span>KRA eTIMS VSCU Desk</span>
          </button>
        </div>
      </div>

      {activeTab === 'pos_activations' ? (
        <PosActivationWorkspace csrfToken={csrfToken} isPlatformOwner={true} />
      ) : null}

      {activeTab === 'integrations' ? (
        <IntegrationWorkspace csrfToken={csrfToken} />
      ) : null}

      {activeTab === 'etims' ? (
        <div style={{ padding: '16px 0' }}>
          <EtimsWorkspaceTab csrfToken={csrfToken} />
        </div>
      ) : null}
    </div>
  );
}
