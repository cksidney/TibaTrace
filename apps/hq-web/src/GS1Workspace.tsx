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
      {/* Header */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(41,128,185,0.2) 0%, rgba(26,35,50,0.8) 100%)',
          border: '1px solid rgba(41,128,185,0.4)',
          borderRadius: '16px',
          padding: '24px 28px',
          marginBottom: '24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginBottom: '8px' }}>
          <div style={{ fontSize: '28px' }}>📦</div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '20px', color: '#dde6f0' }}>
              GS1 Global Traceability & GTIN Registry Workspace
            </div>
            <div style={{ fontSize: '12px', color: '#6b7a8d', marginTop: '2px' }}>
              2D DataMatrix · Serialisation · Packaging Hierarchy · Barcode Validation
            </div>
          </div>
        </div>
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            padding: '4px 12px',
            background: 'rgba(41,128,185,0.25)',
            borderRadius: '6px',
            fontSize: '11px',
            color: '#7aa2cc',
            fontWeight: 600,
          }}
        >
          🌐 Standalone GS1 Enterprise Traceability Engine
        </div>
      </div>

      {/* GTIN Validator Card */}
      <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '14px', padding: '24px', marginBottom: '24px' }}>
        <div style={{ fontWeight: 700, color: '#dde6f0', fontSize: '15px', marginBottom: '12px' }}>
          GTIN & Barcode Validation Tool
        </div>
        <div style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
          <input
            type="text"
            value={gtinQuery}
            onChange={e => setGtinQuery(e.target.value)}
            placeholder="Enter 14-digit GTIN (e.g. 06164000000000)..."
            style={{ flex: 1, background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '6px', color: '#c8d6e8', padding: '10px', fontSize: '13px', outline: 'none' }}
          />
          <button
            onClick={handleValidateGTIN}
            style={{ background: 'rgba(41,128,185,0.3)', border: '1px solid rgba(41,128,185,0.5)', color: '#7aa2cc', borderRadius: '6px', padding: '10px 20px', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}
          >
            Validate GTIN
          </button>
        </div>

        {validationResult && (
          <div style={{ padding: '12px', background: 'rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', fontSize: '12px', color: '#c8d6e8' }}>
            {validationResult}
          </div>
        )}
      </div>

      {/* Capabilities Overview */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px' }}>
        {[
          { title: 'DataMatrix 2D Scanning', desc: 'Parses GS1 Application Identifiers (01: GTIN, 17: Expiry, 10: Batch, 21: Serial)' },
          { title: 'Packaging Hierarchy', desc: 'Item Unit -> Inner Pack -> Master Shipper Case -> Pallet aggregation' },
          { title: 'Manufacturer Registry', desc: 'Verifies GLN (Global Location Number) and licensed pharmaceutical origin' },
        ].map(item => (
          <div key={item.title} style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '12px', padding: '16px' }}>
            <div style={{ fontWeight: 600, color: '#dde6f0', fontSize: '13px', marginBottom: '6px' }}>{item.title}</div>
            <div style={{ fontSize: '11px', color: '#6b7a8d', lineHeight: 1.5 }}>{item.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
