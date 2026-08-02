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
  REGISTRATION_NUMBER: { label: 'PPB Reg No.', placeholder: 'e.g. CTD/12345/2026', icon: '🏛️' },
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
        gap: '10px',
        background: 'var(--panel)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '8px 14px',
        boxShadow: 'var(--shadow)',
        width: '100%',
        maxWidth: '780px',
      }}
    >
      <span style={{ fontSize: '18px', display: 'flex', alignItems: 'center' }}>{fieldInfo.icon}</span>
      <select
        value={selectedField}
        onChange={e => setSelectedField(e.target.value as SearchFieldCategory)}
        style={{
          background: 'var(--canvas)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          color: 'var(--ink)',
          fontSize: '13px',
          fontWeight: 600,
          padding: '8px 12px',
          outline: 'none',
          cursor: 'pointer',
        }}
      >
        {Object.entries(FIELD_LABELS).map(([key, info]) => (
          <option key={key} value={key} style={{ background: 'var(--panel)', color: 'var(--ink)' }}>
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
          color: 'var(--ink)',
          fontSize: '14px',
          outline: 'none',
          padding: '6px 8px',
        }}
      />
      {query && (
        <button
          onClick={handleClear}
          style={{
            background: 'transparent',
            border: 'none',
            color: 'var(--muted)',
            cursor: 'pointer',
            fontSize: '14px',
            padding: '4px 8px',
          }}
          title="Clear search"
          type="button"
        >
          ✕
        </button>
      )}
      <button
        onClick={() => onSearch(selectedField, query)}
        style={{
          background: 'var(--teal-700)',
          border: 'none',
          borderRadius: '8px',
          color: '#ffffff',
          fontSize: '13px',
          fontWeight: 600,
          padding: '8px 18px',
          cursor: 'pointer',
          boxShadow: '0 2px 8px rgba(16, 185, 129, 0.25)',
        }}
        type="button"
      >
        Search
      </button>
    </div>
  );
}
