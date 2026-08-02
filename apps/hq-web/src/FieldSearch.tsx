import { useState } from 'react';

export type SearchFieldCategory =
  | 'GENERIC_NAME'
  | 'BRAND_NAME'
  | 'GTIN'
  | 'BATCH_NUMBER'
  | 'REGISTRATION_NUMBER'
  | 'PATIENT'
  | 'PRESCRIPTION'
  | 'PRACTITIONER'
  | 'BARCODE';

interface FieldSearchProps {
  onSearch: (field: SearchFieldCategory, query: string) => void;
  placeholder?: string;
}

const FIELD_LABELS: Record<SearchFieldCategory, { label: string; placeholder: string; icon: string }> = {
  GENERIC_NAME: { label: 'Generic Name', placeholder: 'e.g. Amoxicillin, Paracetamol...', icon: '🧪' },
  BRAND_NAME: { label: 'Brand Name', placeholder: 'e.g. Augmentin, Panadol...', icon: '💊' },
  GTIN: { label: 'GTIN / GS1', placeholder: '14-digit GTIN e.g. 06164000000000', icon: '📦' },
  BATCH_NUMBER: { label: 'Batch Number', placeholder: 'e.g. BATCH-2026-001', icon: '🏷️' },
  REGISTRATION_NUMBER: { label: 'PPB Registration No.', placeholder: 'e.g. CTD/12345/2026', icon: '🏛️' },
  PATIENT: { label: 'Patient Name / ID', placeholder: 'e.g. John Doe, PAT-001...', icon: '👤' },
  PRESCRIPTION: { label: 'Prescription No.', placeholder: 'e.g. RX-2026-8849', icon: '📋' },
  PRACTITIONER: { label: 'Practitioner / Licence', placeholder: 'e.g. Dr. Kibet, A123456...', icon: '👨‍⚕️' },
  BARCODE: { label: 'Raw Barcode Scan', placeholder: 'Scan or type barcode string...', icon: '🔍' },
};

export function FieldSearch({ onSearch }: FieldSearchProps) {
  const [selectedField, setSelectedField] = useState<SearchFieldCategory>('GENERIC_NAME');
  const [query, setQuery] = useState('');

  const handleClear = () => {
    setQuery('');
    onSearch(selectedField, '');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      onSearch(selectedField, query);
    }
  };

  const fieldInfo = FIELD_LABELS[selectedField];

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        background: 'rgba(0,0,0,0.25)',
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: '10px',
        padding: '6px 12px',
        width: '100%',
        maxWidth: '780px',
      }}
    >
      <span style={{ fontSize: '16px' }}>{fieldInfo.icon}</span>
      <select
        value={selectedField}
        onChange={e => setSelectedField(e.target.value as SearchFieldCategory)}
        style={{
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.1)',
          borderRadius: '6px',
          color: '#7aa2cc',
          fontSize: '12px',
          fontWeight: 600,
          padding: '6px 10px',
          outline: 'none',
          cursor: 'pointer',
        }}
      >
        {Object.entries(FIELD_LABELS).map(([key, info]) => (
          <option key={key} value={key} style={{ background: '#1a2332', color: '#c8d6e8' }}>
            {info.label}
          </option>
        ))}
      </select>
      <input
        type="text"
        value={query}
        onChange={e => setQuery(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={fieldInfo.placeholder}
        style={{
          flex: 1,
          background: 'transparent',
          border: 'none',
          color: '#dde6f0',
          fontSize: '13px',
          outline: 'none',
          padding: '6px 4px',
        }}
      />
      {query && (
        <button
          onClick={handleClear}
          style={{
            background: 'transparent',
            border: 'none',
            color: '#6b7a8d',
            cursor: 'pointer',
            fontSize: '14px',
            padding: '2px 6px',
          }}
          title="Clear search"
        >
          ✕
        </button>
      )}
      <button
        onClick={() => onSearch(selectedField, query)}
        style={{
          background: 'rgba(74,127,165,0.3)',
          border: '1px solid rgba(74,127,165,0.5)',
          borderRadius: '6px',
          color: '#7aa2cc',
          fontSize: '12px',
          fontWeight: 600,
          padding: '6px 14px',
          cursor: 'pointer',
        }}
      >
        Search
      </button>
    </div>
  );
}
