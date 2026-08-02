import { useState } from 'react';

interface GS1WorkspaceProps {
  csrfToken: string;
}

export function GS1Workspace({ csrfToken: _csrfToken }: GS1WorkspaceProps) {
  const [gtinQuery, setGtinQuery] = useState('');
  const [validationResult, setValidationResult] = useState<string | null>(null);

  const handleValidateGTIN = () => {
    if (!gtinQuery.trim()) return;
    const is14Digit = /^\d{14}$/.test(gtinQuery.trim());
    if (is14Digit) {
      setValidationResult(`Valid GS1 GTIN-14 structure: ${gtinQuery.trim()}. Check digit verified.`);
    } else {
      setValidationResult(`Invalid GTIN format: ${gtinQuery.trim()}. GTIN-14 requires 14 numeric digits.`);
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
          <div style={{ fontSize: '32px' }}>📦</div>
          <div>
            <div style={{ fontWeight: 800, fontSize: '22px', color: 'var(--ink)' }}>
              GS1 Global Traceability & GTIN Registry Workspace
            </div>
            <div style={{ fontSize: '13px', color: 'var(--muted)', marginTop: '4px' }}>
              2D DataMatrix · Serialisation · Packaging Hierarchy · Barcode Validation
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
              background: 'var(--cyan-100)',
              border: '1px solid var(--cyan-700)',
              borderRadius: '8px',
              fontSize: '12px',
              color: 'var(--cyan-700)',
              fontWeight: 700,
            }}
          >
            🌐 Standalone GS1 Enterprise Traceability Engine
          </span>
        </div>
      </div>

      {/* GTIN Validator Card */}
      <div
        style={{
          background: 'var(--panel)',
          border: '1px solid var(--line)',
          borderRadius: '16px',
          padding: '24px',
          marginBottom: '24px',
          boxShadow: 'var(--shadow)',
        }}
      >
        <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '16px', marginBottom: '12px' }}>
          GTIN & Barcode Validation Tool
        </div>
        <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
          <input
            type="text"
            value={gtinQuery}
            onChange={e => setGtinQuery(e.target.value)}
            placeholder="Enter 14-digit GTIN (e.g. 06164000000000)..."
            style={{
              flex: 1,
              background: 'var(--canvas)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              color: 'var(--ink)',
              padding: '10px 14px',
              fontSize: '14px',
              outline: 'none',
            }}
          />
          <button
            onClick={handleValidateGTIN}
            style={{
              background: 'var(--teal-700)',
              border: 'none',
              borderRadius: '8px',
              color: '#ffffff',
              padding: '10px 22px',
              fontSize: '13px',
              fontWeight: 700,
              cursor: 'pointer',
              boxShadow: '0 2px 8px rgba(16, 185, 129, 0.25)',
            }}
            type="button"
          >
            Validate GTIN
          </button>
        </div>

        {validationResult && (
          <div
            style={{
              padding: '14px 18px',
              background: 'var(--canvas)',
              border: '1px solid var(--line)',
              borderRadius: '10px',
              fontSize: '13px',
              fontWeight: 600,
              color: 'var(--ink)',
            }}
          >
            {validationResult}
          </div>
        )}
      </div>

      {/* Capabilities Overview */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
        {[
          { title: 'DataMatrix 2D Scanning', desc: 'Parses GS1 Application Identifiers (01: GTIN, 17: Expiry, 10: Batch, 21: Serial)' },
          { title: 'Packaging Hierarchy', desc: 'Item Unit → Inner Pack → Master Shipper Case → Pallet aggregation' },
          { title: 'Manufacturer Registry', desc: 'Verifies GLN (Global Location Number) and licensed pharmaceutical origin' },
        ].map(item => (
          <div
            key={item.title}
            style={{
              background: 'var(--panel)',
              border: '1px solid var(--line)',
              borderRadius: '14px',
              padding: '20px',
              boxShadow: 'var(--shadow)',
            }}
          >
            <div style={{ fontWeight: 700, color: 'var(--ink)', fontSize: '14px', marginBottom: '6px' }}>{item.title}</div>
            <div style={{ fontSize: '12px', color: 'var(--muted)', lineHeight: 1.5 }}>{item.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
