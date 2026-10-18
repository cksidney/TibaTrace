import { useEffect, useRef, useState, type FormEvent } from 'react';
import { PosIcon } from './PosIcon.js';

const BASE = '/api/pos/dispensing/intake/';
type Choice = { id: string; name: string; unit?: string };
interface IntakeOptions {
  branch: Choice; capabilities: Record<string, boolean>;
  patients: Choice[]; practitioners: Choice[]; products: Choice[]; stores: Choice[];
  orders: { id: string; order_number: string; total: string }[];
  feeds: { code: string; available: boolean; message: string }[];
  max_file_bytes: number; max_total_bytes: number; max_files: number;
  upload_notice?: string;
}
interface RxRecord {
  id: string; reference: string; patient_name: string; patient_number: string; prescriber_name: string;
  prescription_date: string; source_channel: string; status: string;
  legal_state: string; clinical_state: string; verification_state: string;
  items?: { medicine: string; quantity: string; unit: string; directions: string }[];
  documents?: { id: string; name: string; content_type: string; size_bytes: number; malware_scan_status?: string }[];
  legal_findings?: { code: string; message: string }[];
  clinical_findings?: { id: string; severity: string; explanation: string; resolution_status: string }[];
}
type Line = { sku: string; quantity: string; directions: string };
type SavedCommand = { path: string; body: Record<string, unknown> };

export async function encodeRxFile(file: File) {
  const contentType = file.type || (/\.pdf$/i.test(file.name) ? 'application/pdf' : /\.png$/i.test(file.name) ? 'image/png' : 'image/jpeg');
  const content = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader(); reader.onerror = () => reject(Error('The source file could not be read.'));
    reader.onload = () => resolve(String(reader.result).split(',')[1] ?? ''); reader.readAsDataURL(file);
  });
  return { name: file.name, content_type: contentType, content_base64: content };
}

export function PrescriptionIntake({ apiFetch, deviceId, active = true, disabled = false, onEpisodeOpened, onBusyChange }: {
  readonly apiFetch: typeof fetch; readonly deviceId: string; readonly active?: boolean; readonly disabled?: boolean;
  readonly onEpisodeOpened: (id: string) => Promise<void>; readonly onBusyChange?: (busy: boolean) => void;
}) {
  const [options, setOptions] = useState<IntakeOptions | null>(null);
  const [mode, setMode] = useState<'receive' | 'inbox' | null>(null);
  const [source, setSource] = useState('PAPER');
  const [rows, setRows] = useState<RxRecord[]>([]); const [selected, setSelected] = useState<RxRecord | null>(null);
  const [values, setValues] = useState<Record<string, string>>({}); const [query, setQuery] = useState('');
  const [lines, setLines] = useState<Line[]>([{ sku: '', quantity: '', directions: '' }]);
  const [files, setFiles] = useState<File[]>([]); const [original, setOriginal] = useState(false);
  const [busy, setBusy] = useState(false); const [notice, setNotice] = useState('');
  const [uncertain, setUncertain] = useState(false); const [canRetry, setCanRetry] = useState(false);
  const saved = useRef<SavedCommand | null>(null); const commandKey = useRef(crypto.randomUUID());
  const inFlight = useRef(false); const dialog = useRef<HTMLElement>(null);
  const [camera, setCamera] = useState(false); const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [preview, setPreview] = useState<{ url: string; type: string; name: string; text?: string } | null>(null);
  const field = (name: string, value: string) => setValues(previous => ({ ...previous, [name]: value }));

  const read = async <T,>(path: string, body?: Record<string, unknown>): Promise<T> => {
    const response = await apiFetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
    const data: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const messages = Array.isArray(data) ? data : data && typeof data === 'object' ? Object.values(data).flat() : [data];
      const error = new Error(messages.filter(value => typeof value === 'string').join(' ') || 'The prescription action could not be completed.');
      Object.assign(error, { status: response.status }); throw error;
    }
    return data as T;
  };
  const refresh = async (search = '') => {
    const suffix = `?device_id=${encodeURIComponent(deviceId)}&q=${encodeURIComponent(search)}`;
    const [choices, received] = await Promise.all([read<IntakeOptions>(`${BASE}options/${suffix}`), read<RxRecord[]>(`${BASE}${suffix}`)]);
    setOptions(previous => {
      if (!previous) return choices;
      const merge = (a: Choice[], b: Choice[], selectedIds: (string | undefined)[]) => [...new Map([...a.filter(row => selectedIds.includes(row.id)), ...b].map(row => [row.id, row])).values()];
      return { ...choices, patients: merge(previous.patients, choices.patients, [values['patient']]), practitioners: merge(previous.practitioners, choices.practitioners, [values['practitioner']]), products: merge(previous.products, choices.products, lines.map(row => row.sku)) };
    }); setRows(received);
  };
  useEffect(() => { void refresh().catch(error => setNotice(String(error.message))); }, [apiFetch, deviceId]);
  useEffect(() => { if (!active) { setMode(null); setCamera(false); setPreview(null); } }, [active]);
  useEffect(() => {
    if (!mode) return;
    const previous = document.activeElement; dialog.current?.focus();
    return () => { if (previous instanceof HTMLElement) previous.focus(); };
  }, [mode]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);
  useEffect(() => {
    if (!camera) return;
    let cancelled = false;
    void navigator.mediaDevices?.getUserMedia({ video: { facingMode: 'environment', width: { ideal: 1920 } }, audio: false })
      .then(media => { if (cancelled) media.getTracks().forEach(track => track.stop()); else { stream.current = media; if (video.current) video.current.srcObject = media; } })
      .catch(() => { setCamera(false); setNotice('Camera access is unavailable. Upload a prescription photo or scanned file instead.'); });
    if (!navigator.mediaDevices) { setCamera(false); setNotice('No camera is available. Upload a photo or scanned file.'); }
    return () => { cancelled = true; stream.current?.getTracks().forEach(track => track.stop()); stream.current = null; };
  }, [camera]);

  const run = async (operation: () => Promise<void>) => {
    if (inFlight.current) return; inFlight.current = true; setBusy(true); onBusyChange?.(true); setNotice('');
    try { await operation(); } catch (error) { setNotice(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); onBusyChange?.(false); inFlight.current = false; }
  };
  const addFiles = (incoming: File[]) => {
    const combined = [...files, ...incoming];
    if (combined.length > (options?.max_files ?? 5) || combined.some(file => file.size > (options?.max_file_bytes ?? 5 * 1024 * 1024)) || combined.reduce((sum, file) => sum + file.size, 0) > (options?.max_total_bytes ?? 8 * 1024 * 1024)) {
      setNotice('Use up to five files, 5 MB each and 8 MB total.'); return;
    }
    if (incoming.some(file => !/\.(pdf|png|jpe?g)$/i.test(file.name) || (file.type && !['application/pdf', 'image/png', 'image/jpeg'].includes(file.type)))) { setNotice('Choose JPEG, PNG or PDF source files.'); return; }
    setFiles(combined); setNotice('');
  };
  const previewFile = (file: File) => {
    const type = file.type || (/\.pdf$/i.test(file.name) ? 'application/pdf' : /\.png$/i.test(file.name) ? 'image/png' : 'image/jpeg');
    setPreview({ url: URL.createObjectURL(new Blob([file], { type })), name: file.name, type });
  };
  const capture = () => {
    const element = video.current; if (!element?.videoWidth) { setNotice('Wait for the camera image before capturing.'); return; }
    const canvas = document.createElement('canvas'); canvas.width = element.videoWidth; canvas.height = element.videoHeight;
    canvas.getContext('2d')?.drawImage(element, 0, 0);
    canvas.toBlob(blob => { if (blob) addFiles([new File([blob], `prescription-photo-${Date.now()}.jpg`, { type: 'image/jpeg' })]); setCamera(false); }, 'image/jpeg', 0.9);
  };
  const received = (rx: RxRecord) => {
    setSelected(rx); setMode('inbox'); setUncertain(false); setCanRetry(false); saved.current = null;
    setFiles([]); setPreview(null); setOriginal(false); setValues({}); setLines([{ sku: '', quantity: '', directions: '' }]);
    commandKey.current = crypto.randomUUID(); setCamera(false); setNotice('Prescription received for review. It has not been approved for dispensing.');
    void refresh().catch(() => setNotice('Prescription saved. Refresh the intake inbox to reload its current state.'));
  };
  const sendOriginal = async (command: SavedCommand) => {
    try { received(await read<RxRecord>(command.path, command.body)); }
    catch (error) {
      const status = (error as { status?: number }).status;
      if (!status || status >= 500) { setUncertain(true); setCanRetry(false); throw Error('Intake outcome unknown. Check the original intake before submitting another prescription.'); }
      saved.current = null; setUncertain(false); throw error;
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault(); void run(async () => {
      if (uncertain) throw Error('Check the original intake first.');
      if (!navigator.onLine) throw Error('Prescription intake requires connectivity. No source document has been sent.');
      const attachments = await Promise.all(files.map(encodeRxFile));
      const body = source === 'PAPER' ? { device_id: deviceId, idempotency_key: commandKey.current,
        patient: values['patient'], practitioner: values['practitioner'], prescription_number: values['reference'],
        prescription_date: values['date'], prescription_type: values['type'], notes: values['notes'] ?? '',
        original_available: original, items: lines, attachments } : {
        device_id: deviceId, idempotency_key: commandKey.current, provider: source, reference: values['reference'], attachments,
      };
      const command = { path: source === 'PAPER' ? BASE : `${BASE}import/`, body }; saved.current = command;
      await sendOriginal(command);
    });
  };
  const checkOriginal = () => void run(async () => {
    const result = await read<{ found: boolean; prescription: RxRecord | null }>(`${BASE}reconcile/?device_id=${encodeURIComponent(deviceId)}&idempotency_key=${encodeURIComponent(commandKey.current)}`);
    if (result.found && result.prescription) received(result.prescription);
    else { setCanRetry(true); setNotice('No saved intake was found for this command. Retry the original command with its unchanged key.'); }
  });
  const progress = (operation: string, extra: Record<string, unknown> = {}) => void run(async () => {
    if (!selected) return;
    const result = await read<RxRecord & { episode_id?: string }>(`${BASE}${selected.id}/progress/`, { device_id: deviceId, operation, ...extra });
    if (result.episode_id) { setMode(null); await onEpisodeOpened(result.episode_id); }
    else { setSelected(result); await refresh(); }
  });
  const openDocument = (id: string) => void run(async () => {
    if (!selected) return;
    const doc = await read<{ name: string; content_type: string; content_base64: string }>(`${BASE}${selected.id}/source-document/`, { device_id: deviceId, document_id: id });
    if (!['image/jpeg', 'image/png', 'application/pdf', 'text/plain'].includes(doc.content_type)) throw Error('Unsupported source document type.');
    const bytes = Uint8Array.from(atob(doc.content_base64), character => character.charCodeAt(0));
    setPreview({ url: URL.createObjectURL(new Blob([bytes], { type: doc.content_type })), name: doc.name, type: doc.content_type,
      ...(doc.content_type === 'text/plain' ? { text: new TextDecoder().decode(bytes) } : {}) });
  });
  const selectField = (label: string, name: string, choices: Choice[]) => <label>{label}<select required value={values[name] ?? ''} onChange={event => field(name, event.target.value)}><option value="">Select confirmed record</option>{choices.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>;
  const cap = options?.capabilities ?? {};
  const sourcePreview = preview && <div className="pos-rx-preview"><strong>{preview.name}</strong>{preview.text !== undefined ? <pre>{preview.text}</pre> : preview.type === 'application/pdf' ? <iframe src={preview.url} title="Original prescription PDF" /> : <img src={preview.url} alt="Original prescription for clinical review" />}<a href={preview.url} download={preview.name}>Save a copy for authorised review</a><button type="button" className="pos-button" onClick={() => setPreview(null)}>Close document</button></div>;
  return <section className="pos-rx-intake" aria-label="Prescription intake">
    <div><span className="pos-eyebrow">Receive & review</span><strong>Prescription intake</strong><p>Paper, photo, scanned PDF or a configured clinical feed.</p></div>
    <div className="pos-rx-actions"><button className="pos-start-sale" disabled={disabled || busy || !options || !cap['receive']} onClick={() => { setMode('receive'); setSelected(null); }}>Receive prescription</button><button className="pos-button" disabled={disabled || busy || !options} onClick={() => { setMode('inbox'); void run(() => refresh()); }}>Received prescriptions</button></div>
    {notice && !mode && <p role="status">{notice}</p>}
    {mode && <div className="pos-modal-backdrop"><section className="pos-modal pos-rx-dialog" role="dialog" aria-modal="true" aria-labelledby="rx-intake-title" ref={dialog} tabIndex={-1} onKeyDown={event => {
      event.stopPropagation();
      if (event.key === 'Escape' && !busy) { event.stopPropagation(); setMode(null); setCamera(false); setPreview(null); }
      if (event.key === 'Tab') { const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]')]; const first = controls[0], last = controls.at(-1); if (!first) { event.preventDefault(); return; } if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.current)) { event.preventDefault(); last?.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
    }}>
      <header><div><span className="pos-eyebrow">{options?.branch.name}</span><h2 id="rx-intake-title">{mode === 'receive' ? 'Receive prescription' : 'Received prescriptions'}</h2></div><button type="button" className="pos-button" disabled={busy} onClick={() => { setMode(null); setCamera(false); setPreview(null); }}>Close</button></header>
      <p className="pos-payment-help">Every source enters legal and clinical review. Uploading or importing an RX does not verify it or authorise supply.</p>
      {notice && <p className="pos-payment-notice" role="status">{notice}</p>}
      {mode === 'receive' && options ? <>
        <div className="pos-rx-search"><input aria-label="Search intake records" placeholder="Find a patient, prescriber or medicine" value={query} disabled={busy || uncertain} onChange={event => setQuery(event.target.value)} /><button type="button" className="pos-button" disabled={busy || uncertain} onClick={() => void run(() => refresh(query))}>Search records</button></div>
        <form onSubmit={submit}><fieldset disabled={busy || uncertain} className="pos-rx-fields">
          <label>Prescription source<select value={source} onChange={event => setSource(event.target.value)}><option value="PAPER">Original paper / uploaded source</option>{options.feeds.map(feed => <option key={feed.code} value={feed.code} disabled={!feed.available}>{feed.code.replace(/_/g, ' ')}{feed.available ? '' : ' · setup required'}</option>)}</select></label>
          <label>Original RX reference<input required maxLength={source === 'PAPER' ? 80 : 120} value={values['reference'] ?? ''} onChange={event => field('reference', event.target.value)} /></label>
          {source === 'PAPER' && <>
            {selectField('Patient', 'patient', options.patients)}{selectField('Prescriber', 'practitioner', options.practitioners)}
            <label>Prescription date<input type="date" required value={values['date'] ?? ''} onChange={event => field('date', event.target.value)} /></label>
            <label>Prescription type<select required value={values['type'] ?? ''} onChange={event => field('type', event.target.value)}><option value="">Select actual type</option>{['ACUTE','REPEAT','CHRONIC','CONTROLLED','DISCHARGE','EMERGENCY','VETERINARY','INTERNAL'].map(type => <option key={type} value={type}>{type}</option>)}</select></label>
            <div className="pos-rx-wide">{lines.map((line, index) => <div className="pos-rx-line" key={index}>
              <label>Prescribed medicine / pack<select required value={line.sku} onChange={event => setLines(previous => previous.map((row, i) => i === index ? { ...row, sku: event.target.value } : row))}><option value="">Choose exact product</option>{options.products.map(row => <option key={row.id} value={row.id}>{row.name} · {row.unit}</option>)}</select></label>
              <label>Authorised quantity<input type="number" required min="0.001" step="0.001" value={line.quantity} onChange={event => setLines(previous => previous.map((row, i) => i === index ? { ...row, quantity: event.target.value } : row))} /></label>
              <label className="pos-rx-wide">Directions as prescribed<textarea required value={line.directions} onChange={event => setLines(previous => previous.map((row, i) => i === index ? { ...row, directions: event.target.value } : row))} /></label>
              {lines.length > 1 && <button type="button" className="pos-button" onClick={() => setLines(previous => previous.filter((_, i) => i !== index))}>Remove unsaved line</button>}
            </div>)}<button type="button" className="pos-button" disabled={lines.length >= 50} onClick={() => setLines(previous => [...previous, { sku: '', quantity: '', directions: '' }])}>Add prescribed medicine</button></div>
            <label className="pos-rx-wide">Intake notes<textarea value={values['notes'] ?? ''} onChange={event => field('notes', event.target.value)} maxLength={4000} /></label>
          </>}
          <section className="pos-rx-upload pos-rx-wide"><h3>Original prescription evidence</h3><p>Attach a readable scan, photo or PDF. Transcribe and check the prescribed lines; no automatic OCR approval is performed.</p>
            {options.upload_notice && <p className="pos-payment-notice" role="status">{options.upload_notice}</p>}
            <label>Upload scan / photo / PDF<input type="file" accept="image/jpeg,image/png,application/pdf" multiple disabled={!cap['upload']} onChange={event => { addFiles([...event.target.files ?? []]); event.target.value = ''; }} /></label>
            <button type="button" className="pos-button" disabled={!cap['upload']} onClick={() => setCamera(true)}>Take prescription photo</button>
            {camera && <div className="pos-rx-camera"><video ref={video} muted playsInline autoPlay aria-label="Prescription camera preview" /><button type="button" className="pos-button" onClick={capture}>Capture photo</button><button type="button" className="pos-button" onClick={() => setCamera(false)}>Stop camera</button></div>}
            <ul>{files.map((file, index) => <li key={`${file.name}:${index}`}><span>{file.name} · {(file.size / 1024).toFixed(0)} KB</span><button type="button" className="pos-button" onClick={() => previewFile(file)}>Preview {file.name}</button><button type="button" className="pos-button" onClick={() => { setFiles(previous => previous.filter((_, i) => i !== index)); setPreview(null); }}>Remove {file.name}</button></li>)}</ul>
            {sourcePreview}
            <small>Up to five files · 5 MB per file · 8 MB total. Files are validated and stored under the patient’s tenant.</small>
          </section>
          {source === 'PAPER' && <label className="pos-rx-wide pos-rx-confirm"><input type="checkbox" checked={original} onChange={event => setOriginal(event.target.checked)} /> The genuine original is available for pharmacist review.</label>}
          <button type="submit" className="pos-start-sale pos-rx-wide" disabled={!navigator.onLine || (source === 'PAPER' && !original && files.length === 0)}>{busy ? 'Receiving…' : source === 'PAPER' ? 'Receive for review' : 'Import for review'}</button>
        </fieldset></form>
        {uncertain && <div className="pos-payment-notice" role="alert"><p>The original intake needs reconciliation. Keep this command unchanged.</p><button type="button" className="pos-button" disabled={busy} onClick={checkOriginal}>Check original intake</button>{canRetry && <button type="button" className="pos-button" disabled={busy} onClick={() => void run(async () => { if (saved.current) await sendOriginal(saved.current); })}>Retry original intake</button>}</div>}
        {options.feeds.filter(feed => !feed.available).map(feed => <p className="pos-payment-help" key={feed.code}>{feed.code.replace(/_/g, ' ')}: {feed.message}</p>)}
      </> : <>
        <div className="pos-rx-search"><input aria-label="Search received prescriptions" value={query} onChange={event => setQuery(event.target.value)} placeholder="RX reference or patient" /><button className="pos-button" disabled={busy} onClick={() => void run(() => refresh(query))}>Search inbox</button></div>
        {selected ? <section className="pos-rx-review"><button className="pos-button" disabled={busy} onClick={() => { setSelected(null); setPreview(null); }}>Back to inbox</button><h3>{selected.reference}</h3><p><b>{selected.patient_name}</b> · {selected.patient_number} · {selected.prescriber_name}</p>
          <div className="pos-rx-states"><span>Legal: {selected.legal_state}</span><span>Clinical: {selected.clinical_state}</span><span>Pharmacist: {selected.verification_state}</span></div>
          {selected.items?.map((item, index) => <article key={index}><b>{item.medicine} · {item.quantity} {item.unit}</b><p>{item.directions}</p></article>)}
          <h4>Source documents</h4>{selected.documents?.length ? selected.documents.map(doc => <button key={doc.id} type="button" className="pos-button" disabled={busy || !cap['read_documents']} onClick={() => openDocument(doc.id)}>{doc.name}{doc.malware_scan_status === 'NOT_SCANNED' ? ' · Not malware scanned' : doc.malware_scan_status === 'NOT_APPLICABLE' ? ' · Intake record' : ''}</button>) : <p>The original is held for physical review; no attachment was uploaded.</p>}
          {sourcePreview}
          {selected.legal_findings?.map((finding, index) => <p className="pos-payment-notice" key={index}>{finding.code}: {finding.message}</p>)}
          {selected.clinical_findings?.map(finding => <p className="pos-payment-notice" key={finding.id}>{finding.severity} · {finding.explanation} · {finding.resolution_status}</p>)}
          <div className="pos-rx-actions"><button type="button" className="pos-button" disabled={busy || !cap['validate'] || selected.verification_state === 'VERIFIED'} onClick={() => progress('validate')}>Run legal validation</button><button type="button" className="pos-button" disabled={busy || !cap['review'] || selected.legal_state !== 'PASSED' || selected.verification_state === 'VERIFIED'} onClick={() => progress('review')}>Start clinical review</button></div>
          {cap['review'] && selected.legal_state === 'PASSED' && selected.clinical_state !== 'NOT_STARTED' && selected.verification_state !== 'VERIFIED' && <form className="pos-rx-fields" onSubmit={event => { event.preventDefault(); progress('review', { outcome: values['outcome'], notes: values['review_notes'] }); }}><label>Pharmacist review outcome<select required value={values['outcome'] ?? ''} onChange={event => field('outcome', event.target.value)}><option value="">Select clinical decision</option>{['APPROVED','APPROVED_WITH_COUNSELLING','INTERVENTION_REQUIRED','PRESCRIBER_CONTACT_REQUIRED','PATIENT_CONTACT_REQUIRED','REJECTED','ON_HOLD'].map(outcome => <option key={outcome} value={outcome}>{outcome.replace(/_/g, ' ')}</option>)}</select></label><label>Clinical rationale<textarea required value={values['review_notes'] ?? ''} onChange={event => field('review_notes', event.target.value)} /></label><button className="pos-button" disabled={busy}>Record review outcome</button><p>Unresolved clinical findings must be addressed in the governed pharmacist workbench before approval.</p></form>}
          <button type="button" className="pos-start-sale" disabled={busy || !cap['verify'] || selected.legal_state !== 'PASSED' || selected.clinical_state !== 'COMPLETED' || selected.verification_state === 'VERIFIED'} onClick={() => progress('verify', { notes: values['review_notes'] ?? '' })}>Pharmacist: verify prescription</button>
          {selected.verification_state === 'VERIFIED' && <form className="pos-rx-fields" onSubmit={event => { event.preventDefault(); progress('open_episode', { store: values['store'], order: values['order'] }); }}>{selectField('Dispensing store', 'store', options?.stores ?? [])}{selectField('Approved priced order', 'order', options?.orders.map(order => ({ id: order.id, name: `${order.order_number} · ${order.total}` })) ?? [])}<p className="pos-rx-wide">Confirm this order covers the prescribed products and quantities. Opening an episode does not collect payment or release stock.</p><button className="pos-start-sale" disabled={busy || !cap['open_episode']}>Open dispensing episode</button></form>}
        </section> : <div className="pos-rx-inbox">{rows.length ? rows.map(row => <button className="pos-rx-inbox-row" disabled={busy} key={row.id} onClick={() => void run(async () => { setSelected(await read<RxRecord>(`${BASE}${row.id}/?device_id=${encodeURIComponent(deviceId)}`)); setValues({}); })}><span><b>{row.patient_name}</b><small>{row.reference} · {row.prescription_date} · {row.source_channel}</small></span><span>{row.status.replace(/_/g, ' ')} <PosIcon name="arrow" size={16} /></span></button>) : <p>No prescriptions found in this branch. Receive a prescription or refine the search.</p>}</div>}
      </>}
    </section></div>}
  </section>;
}
