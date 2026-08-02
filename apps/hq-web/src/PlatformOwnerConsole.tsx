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
        headers: { 'Accept': 'application/json' },
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
          'Accept': 'application/json',
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
          'Accept': 'application/json',
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
      {/* Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(142,68,173,0.2) 0%, rgba(44,62,80,0.4) 100%)',
          border: '1px solid rgba(142,68,173,0.4)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '8px' }}>
          <div style={{ fontSize: '28px' }}>👑</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '20px', color: '#e0b0ff' }}>
              Platform Owner Governance Console
            </div>
            <div style={{ fontSize: '12px', color: '#a0a0c0', marginTop: '2px' }}>
              Restricted Global Administrative Surface · Fail-Closed Authority
            </div>
          </div>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 12px',
            background: 'rgba(142,68,173,0.3)',
            borderRadius: '6px',
            fontSize: '11px',
            color: '#e0b0ff',
            fontWeight: 600,
          }}
        >
          🔒 Platform Owner Role Enforced — Tenant Admins Blocked
        </div>
      </div>

      {actionMessage && (
        <div style={{ padding: '12px', background: 'rgba(74,127,165,0.2)', color: '#7aa2cc', border: '1px solid rgba(74,127,165,0.4)', borderRadius: '8px', marginBottom: '20px', fontSize: '12px' }}>
          ℹ️ {actionMessage}
        </div>
      )}

      {/* Control Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '28px' }}>
        {/* Provider Activation Approval */}
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🔑</span> National Provider Activation Governance (11 Stages)
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d', marginBottom: '16px', lineHeight: 1.5 }}>
            Advance national health provider activations through the required security and compliance gates.
          </div>

          {loading ? (
            <div style={{ fontSize: '12px', color: '#6b7a8d' }}>Loading activation requests...</div>
          ) : activations.length === 0 ? (
            <div style={{ fontSize: '12px', color: '#6b7a8d', background: 'rgba(0,0,0,0.2)', padding: '14px', borderRadius: '8px' }}>
              No open activation requests pending review.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {activations.map(act => (
                <div key={act.id} style={{ background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontWeight: 600, color: '#c8d6e8', fontSize: '13px' }}>{act.provider_type}</span>
                    <span style={{ fontSize: '11px', color: '#f39c12', fontWeight: 600 }}>{act.state}</span>
                  </div>
                  <div style={{ fontSize: '11px', color: '#6b7a8d', marginBottom: '10px' }}>
                    Requested by: {act.requested_by || 'System Admin'}
                  </div>
                  <div style={{ display: 'flex', gap: '6px' }}>
                    <button
                      onClick={() => handleAdvanceState(act.id, 'SECURITY_REVIEW')}
                      style={{ background: 'rgba(41,128,185,0.3)', border: '1px solid rgba(41,128,185,0.5)', color: '#7aa2cc', borderRadius: '6px', padding: '4px 10px', fontSize: '11px', cursor: 'pointer', fontWeight: 600 }}
                    >
                      Security Review
                    </button>
                    <button
                      onClick={() => handleAdvanceState(act.id, 'SANDBOX_PASSED')}
                      style={{ background: 'rgba(39,174,96,0.3)', border: '1px solid rgba(39,174,96,0.5)', color: '#66dd88', borderRadius: '6px', padding: '4px 10px', fontSize: '11px', cursor: 'pointer', fontWeight: 600 }}
                    >
                      Sandbox Passed
                    </button>
                    <button
                      onClick={() => handleAdvanceState(act.id, 'REJECTED')}
                      style={{ background: 'rgba(231,76,60,0.3)', border: '1px solid rgba(231,76,60,0.5)', color: '#e74c3c', borderRadius: '6px', padding: '4px 10px', fontSize: '11px', cursor: 'pointer', fontWeight: 600 }}
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
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(231,76,60,0.2)', borderRadius: '14px', padding: '20px' }}>
          <div style={{ fontWeight: 700, color: '#e74c3c', fontSize: '15px', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🚨</span> Emergency Provider Kill Switch
          </div>
          <div style={{ fontSize: '12px', color: '#6b7a8d', marginBottom: '16px', lineHeight: 1.5 }}>
            Immediately suspend operations for a national integration provider in case of security incident or regulatory notice.
          </div>

          <div style={{ marginBottom: '12px' }}>
            <label style={{ display: 'block', fontSize: '11px', color: '#8894a6', marginBottom: '4px' }}>
              Reason for Kill Switch Activation
            </label>
            <input
              type="text"
              value={killSwitchReason}
              onChange={e => setKillSwitchReason(e.target.value)}
              placeholder="e.g. Regulatory revocation notice received from PPB..."
              style={{ width: '100%', background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', color: '#c8d6e8', padding: '8px', fontSize: '12px', outline: 'none' }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {['DHA_HIE', 'DHA_HWR', 'PPB_PREMISES', 'PPB_RECALLS'].map(prov => (
              <button
                key={prov}
                onClick={() => handleActivateKillSwitch(prov)}
                style={{ background: 'rgba(231,76,60,0.2)', border: '1px solid rgba(231,76,60,0.4)', color: '#e74c3c', borderRadius: '6px', padding: '8px', fontSize: '11px', fontWeight: 700, cursor: 'pointer' }}
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
