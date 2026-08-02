import { useCallback, useEffect, useState } from 'react';

interface PlatformOwnerConsoleProps {
  csrfToken: string;
}

interface ActivationRequest {
  id: string;
  provider_type: string;
  state: string;
  requested_by: string;
  created_at: string;
  notes: string;
}

export function PlatformOwnerConsole({ csrfToken: _csrfToken }: PlatformOwnerConsoleProps) {
  const [activations, setActivations] = useState<ActivationRequest[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [killSwitchReason, setKillSwitchReason] = useState<string>('');

  const fetchActivations = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/nif/platform/activations/', {
        headers: { Accept: 'application/json' },
      });
      if (res.ok) {
        const data = await res.json();
        setActivations(Array.isArray(data) ? data : data.results || []);
      }
    } catch {
      // Fallback
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchActivations();
  }, [fetchActivations]);

  const handleAdvanceState = async (id: string, toState: string) => {
    setActionMessage(null);
    try {
      const res = await fetch(`/api/nif/platform/activations/${id}/advance/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ to_state: toState, notes: 'Advanced by Platform Owner console.' }),
      });
      if (res.ok) {
        setActionMessage(`Successfully advanced activation ${id} to ${toState}.`);
        void fetchActivations();
      } else {
        const err = await res.json();
        setActionMessage(`Failed to advance state: ${err.detail || JSON.stringify(err)}`);
      }
    } catch {
      setActionMessage('Network error while advancing activation state.');
    }
  };

  const handleActivateKillSwitch = async (providerType: string) => {
    if (!killSwitchReason.trim()) {
      setActionMessage('Please enter a reason before activating emergency kill switch.');
      return;
    }
    setActionMessage(null);
    try {
      const res = await fetch(`/api/nif/platform/providers/${providerType}/enable-kill-switch/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ reason: killSwitchReason }),
      });
      if (res.ok) {
        setActionMessage(`Emergency Kill Switch activated for ${providerType}. Operations suspended.`);
        setKillSwitchReason('');
      } else {
        setActionMessage('Failed to activate kill switch.');
      }
    } catch {
      setActionMessage('Network error while activating kill switch.');
    }
  };

  return (
    <div style={{ padding: '0 0 40px' }}>
      {/* Header Banner */}
      <div
        style={{
          background: 'var(--panel)',
          border: '1px solid var(--line)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
          boxShadow: 'var(--shadow)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '8px' }}>
          <div style={{ fontSize: '32px' }}>👑</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '22px', color: 'var(--ink)' }}>
              Platform Owner Governance Console
            </div>
            <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
              Restricted Global Administrative Surface · Fail-Closed Authority
            </div>
          </div>
        </div>
        <div style={{ marginTop: '12px' }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: '6px 14px',
              background: 'var(--violet-100)',
              border: '1px solid var(--violet-700)',
              borderRadius: '8px',
              fontSize: '12px',
              color: 'var(--violet-700)',
              fontWeight: 700,
            }}
          >
            🔒 Platform Owner Role Enforced — Tenant Admins Blocked
          </span>
        </div>
      </div>

      {actionMessage && (
        <div
          style={{
            padding: '14px 18px',
            background: 'var(--cyan-100)',
            color: 'var(--cyan-700)',
            border: '1px solid var(--cyan-700)',
            borderRadius: '10px',
            marginBottom: '20px',
            fontSize: '13px',
            fontWeight: 600,
          }}
        >
          ℹ️ {actionMessage}
        </div>
      )}

      {/* Control Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '28px' }}>
        {/* Provider Activation Approval */}
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🔑</span> National Provider Activation Governance (11 Stages)
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', marginBottom: '20px', lineHeight: 1.5 }}>
            Advance national health provider activations through the required security and compliance gates.
          </div>

          {loading ? (
            <div style={{ fontSize: '13px', color: 'var(--muted)' }}>Loading activation requests...</div>
          ) : activations.length === 0 ? (
            <div
              style={{
                fontSize: '13px',
                color: 'var(--muted)',
                background: 'var(--canvas)',
                border: '1px solid var(--line-soft)',
                padding: '18px',
                borderRadius: '10px',
                textAlign: 'center',
              }}
            >
              No open activation requests pending review.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {activations.map(act => (
                <div
                  key={act.id}
                  style={{
                    background: 'var(--canvas)',
                    border: '1px solid var(--line)',
                    borderRadius: '10px',
                    padding: '16px',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <span style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '14px' }}>{act.provider_type}</span>
                    <span
                      style={{
                        fontSize: '11px',
                        color: 'var(--amber-700)',
                        background: 'var(--amber-100)',
                        padding: '3px 10px',
                        borderRadius: '6px',
                        fontWeight: 700,
                      }}
                    >
                      {act.state}
                    </span>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--muted)', marginBottom: '12px' }}>
                    Requested by: {act.requested_by || 'System Admin'}
                  </div>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={() => handleAdvanceState(act.id, 'SECURITY_REVIEW')}
                      style={{
                        background: 'var(--teal-100)',
                        border: '1px solid var(--teal-700)',
                        color: 'var(--teal-700)',
                        borderRadius: '8px',
                        padding: '6px 14px',
                        fontSize: '12px',
                        cursor: 'pointer',
                        fontWeight: 700,
                      }}
                      type="button"
                    >
                      Security Review
                    </button>
                    <button
                      onClick={() => handleAdvanceState(act.id, 'SANDBOX_PASSED')}
                      style={{
                        background: 'var(--teal-700)',
                        border: 'none',
                        color: '#ffffff',
                        borderRadius: '8px',
                        padding: '6px 14px',
                        fontSize: '12px',
                        cursor: 'pointer',
                        fontWeight: 700,
                      }}
                      type="button"
                    >
                      Sandbox Passed
                    </button>
                    <button
                      onClick={() => handleAdvanceState(act.id, 'REJECTED')}
                      style={{
                        background: 'var(--red-100)',
                        border: '1px solid var(--red-500)',
                        color: 'var(--danger-ink)',
                        borderRadius: '8px',
                        padding: '6px 14px',
                        fontSize: '12px',
                        cursor: 'pointer',
                        fontWeight: 700,
                      }}
                      type="button"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Emergency Kill Switch */}
        <div
          style={{
            background: 'var(--panel)',
            border: '1px solid var(--red-500)',
            borderRadius: '16px',
            padding: '24px',
            boxShadow: 'var(--shadow)',
          }}
        >
          <div style={{ fontWeight: 700, color: 'var(--danger-ink)', fontSize: '16px', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🚨</span> Emergency Provider Kill Switch
          </div>
          <div style={{ fontSize: '13px', color: 'var(--muted)', marginBottom: '20px', lineHeight: 1.5 }}>
            Immediately suspend operations for a national integration provider in case of security incident or regulatory notice.
          </div>

          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: 'var(--ink)', marginBottom: '6px' }}>
              Reason for Kill Switch Activation
            </label>
            <input
              type="text"
              value={killSwitchReason}
              onChange={e => setKillSwitchReason(e.target.value)}
              placeholder="e.g. Regulatory revocation notice received from PPB..."
              style={{
                width: '100%',
                background: 'var(--canvas)',
                border: '1px solid var(--line)',
                borderRadius: '8px',
                color: 'var(--ink)',
                padding: '10px 12px',
                fontSize: '13px',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            {['DHA_HIE', 'DHA_HWR', 'PPB_PREMISES', 'PPB_RECALLS'].map(prov => (
              <button
                key={prov}
                onClick={() => handleActivateKillSwitch(prov)}
                style={{
                  background: 'var(--red-100)',
                  border: '1px solid var(--red-500)',
                  color: 'var(--danger-ink)',
                  borderRadius: '8px',
                  padding: '10px',
                  fontSize: '12px',
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
                type="button"
              >
                Kill {prov}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
