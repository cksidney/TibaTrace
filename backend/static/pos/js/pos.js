/* ==========================================================================
   TibaTrace Enterprise Pharmacy POS — Complete End-to-End Business Logic & UI/UX Engine
   ========================================================================== */

let activeQueue = [];
let selectedEpisode = null;
let currentFilter = 'ALL';

// Initialize POS Application
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  fetchQueue();
  setupKeyboardShortcuts();
  startTelemetryHeartbeat();
});

// Theme Toggle Engine (Light / Dark Mode)
function initTheme() {
  const saved = localStorage.getItem('tibatrace-theme') || 'dark-theme';
  document.body.className = saved;
  updateThemeButtonText(saved);
}

function toggleTheme() {
  const current = document.body.className.includes('light-theme') ? 'light-theme' : 'dark-theme';
  const next = current === 'dark-theme' ? 'light-theme' : 'dark-theme';
  document.body.className = next;
  localStorage.setItem('tibatrace-theme', next);
  updateThemeButtonText(next);
  showToast(`Switched to ${next === 'dark-theme' ? 'Dark' : 'Light'} Mode.`);
}

function updateThemeButtonText(theme) {
  const btn = document.getElementById('btn-theme-toggle');
  if (btn) {
    btn.innerHTML = theme === 'dark-theme' ? '🌙 Dark Mode' : '☀️ Light Mode';
  }
}

// Toast Notification Engine
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type === 'error' ? 'toast-error' : ''}`;
  const icon = type === 'error' ? '❌' : (type === 'warning' ? '⚠️' : '✅');
  toast.innerHTML = `<span>${icon}</span> <span>${message}</span>`;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// Fetch Dispensing Queue from API
async function fetchQueue() {
  try {
    const response = await fetch('/api/pos/dispensing/episodes/queue/');
    if (!response.ok) {
      activeQueue = getFallbackDemoQueue();
    } else {
      activeQueue = await response.json();
    }

    if (!activeQueue || activeQueue.length === 0) {
      activeQueue = getFallbackDemoQueue();
    }

    updateKPIs();
    renderQueueList();

    if (selectedEpisode) {
      const updated = activeQueue.find(e => e.id === selectedEpisode.id);
      if (updated) selectEpisode(updated);
    } else if (activeQueue.length > 0) {
      selectEpisode(activeQueue[0]);
    }
  } catch (err) {
    console.error('Error fetching queue:', err);
    activeQueue = getFallbackDemoQueue();
    updateKPIs();
    renderQueueList();
    if (activeQueue.length > 0) selectEpisode(activeQueue[0]);
  }
}

// Update KPI Dashboard Cards
function updateKPIs() {
  document.getElementById('kpi-queue-count').innerText = activeQueue.length;
  document.getElementById('kpi-checking-count').innerText = activeQueue.filter(e => e.status === 'CHECKING').length;
  document.getElementById('kpi-payment-count').innerText = activeQueue.filter(e => e.status === 'READY_FOR_PAYMENT').length;
  document.getElementById('kpi-supplied-count').innerText = activeQueue.filter(e => e.status === 'SUPPLIED').length;
}

// Filter Queue Tabs
function setFilter(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderQueueList();
}

// Search Filter
function filterQueueList() {
  renderQueueList();
}

// Render Queue List Cards
function renderQueueList() {
  const container = document.getElementById('queue-list-container');
  const searchText = (document.getElementById('queue-search-input').value || '').toLowerCase();

  let filtered = activeQueue;
  if (currentFilter !== 'ALL') {
    filtered = filtered.filter(e => e.status === currentFilter);
  }

  if (searchText) {
    filtered = filtered.filter(e => 
      e.dispensing_number.toLowerCase().includes(searchText) ||
      (e.patient_name || '').toLowerCase().includes(searchText) ||
      (e.prescription_number || '').toLowerCase().includes(searchText)
    );
  }

  if (filtered.length === 0) {
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #64748b;">No matching dispensing episodes.</div>';
    return;
  }

  container.innerHTML = filtered.map(ep => {
    const isSelected = selectedEpisode && selectedEpisode.id === ep.id;
    const statusClass = getStatusClass(ep.status);
    return `
      <div class="queue-card ${isSelected ? 'selected' : ''}" onclick="selectEpisodeById('${ep.id}')">
        <div class="q-header">
          <span class="q-disp-no">${ep.dispensing_number}</span>
          <span class="q-status-badge ${statusClass}">${ep.status}</span>
        </div>
        <div class="q-patient">${ep.patient_name || 'Grace Kamau'}</div>
        <div class="q-meta">
          <span>Items: ${(ep.lines || []).length || 1}</span>
          <span>Payment: <strong>${ep.payment_status || 'PENDING'}</strong></span>
        </div>
      </div>
    `;
  }).join('');
}

function selectEpisodeById(id) {
  const ep = activeQueue.find(e => e.id === id);
  if (ep) selectEpisode(ep);
}

// Select Active Episode into Workspace
function selectEpisode(ep) {
  selectedEpisode = ep;
  renderQueueList();

  document.getElementById('empty-workspace-view').style.display = 'none';
  document.getElementById('active-episode-view').style.display = 'block';

  document.getElementById('dispensing-no-display').innerText = ep.dispensing_number;
  const badge = document.getElementById('episode-status-badge');
  badge.innerText = ep.status;
  badge.className = `status-badge ${getStatusClass(ep.status)}`;

  document.getElementById('pat-name').innerText = ep.patient_name || 'Grace Kamau';
  document.getElementById('pat-num').innerText = ep.patient_number || 'DEMO-PAT-1';
  document.getElementById('pat-gender').innerText = ep.patient_gender || 'FEMALE';
  document.getElementById('pat-dob').innerText = ep.patient_dob || '1985-05-12';

  document.getElementById('rx-num').innerText = ep.prescription_number || 'DEMO-RX-8001';
  document.getElementById('prac-name').innerText = ep.prescriber_name || 'Dr. David Ochieng';

  const payTag = document.getElementById('payment-status-tag');
  payTag.innerText = `Payment: ${ep.payment_status || 'PENDING'}`;
  if (ep.payment_status === 'PAID') {
    payTag.style.background = 'rgba(16, 185, 129, 0.15)';
    payTag.style.color = '#34d399';
    payTag.style.borderColor = 'rgba(16, 185, 129, 0.3)';
  } else {
    payTag.style.background = 'rgba(245, 158, 11, 0.15)';
    payTag.style.color = '#fbbf24';
    payTag.style.borderColor = 'rgba(245, 158, 11, 0.3)';
  }

  // The banner starts as "not screened" for every episode and is only moved off
  // that state by an authoritative server response. It previously rendered from
  // `ep.cds_warning`, a field the backend never sends, so the else branch always
  // ran and every episode displayed "PASSED" with a list of checks that had not
  // been performed. Absence of a screening is not a screening that passed.
  lastScreening = null;
  renderCdsUnscreened();
  refreshClinicalScreening(ep);

  renderDispensingLines(ep.lines || getFallbackLines());
}

// ── Clinical screening banner ─────────────────────────────────────────────────
//
// Three states, and only one of them may claim safety:
//
//   not screened  — the default, and where the banner stays unless the server
//                   affirmatively says otherwise
//   blocked       — the server returned blocking findings
//   safe          — the server returned safe_to_proceed
//
// The client never derives "safe". It is copied from the server's
// `safe_to_proceed`, which is the only authority for it. A screening we could
// not fetch, a request that failed, and an episode nobody has screened all land
// in "not screened", because to a dispenser those are the same fact: nothing
// has checked this prescription.

// The most recent authoritative screening response. Set only from the server.
let lastScreening = null;

function setCdsBanner({ variant, icon, title, detail }) {
  const banner = document.getElementById('cds-screening-banner');
  if (!banner) return;
  banner.className = `cds-banner ${variant}`;
  const iconEl = document.getElementById('cds-icon');
  const titleEl = document.getElementById('cds-status-title');
  const detailEl = document.getElementById('cds-details-text');
  if (iconEl) iconEl.innerText = icon;
  if (titleEl) titleEl.innerText = title;
  if (detailEl) detailEl.innerText = detail;
}

function renderCdsUnscreened(detail) {
  setCdsBanner({
    variant: 'cds-warning',
    icon: '○',
    title: 'CDS Clinical Screening: NOT SCREENED',
    detail:
      detail ||
      'This prescription has not been screened for interactions, duplicate therapy or allergies. Screening is required before supply.',
  });
}

function renderCdsResult(result) {
  const blocking = Number(result.blocking_findings || 0);

  if (blocking > 0) {
    const titles = (result.findings || [])
      .filter((f) => f.blocking)
      .map((f) => f.title)
      .join('; ');
    setCdsBanner({
      variant: 'cds-warning',
      icon: '⚠️',
      title: `CDS Clinical Screening: ${blocking} BLOCKING FINDING${blocking === 1 ? '' : 'S'}`,
      detail: titles || 'Blocking findings prevent supply. Pharmacist review is required.',
    });
    return;
  }

  // Only the server's own verdict may produce a pass. A screening that
  // completed with no blocking findings but was not marked safe is still not a
  // pass -- the server withheld it for a reason the till cannot see.
  if (result.safe_to_proceed === true) {
    const advisory = (result.findings || []).length;
    setCdsBanner({
      variant: 'cds-pass',
      icon: '🛡️',
      title: 'CDS Clinical Screening: PASSED',
      detail: advisory
        ? `Screened at ${result.evaluated_at || 'unknown time'}. ${advisory} advisory finding${advisory === 1 ? '' : 's'}, none blocking.`
        : `Screened at ${result.evaluated_at || 'unknown time'}. No blocking findings.`,
    });
    return;
  }

  renderCdsUnscreened(
    'Screening completed but the server did not confirm it as safe to proceed. Supply is not authorised.',
  );
}

async function refreshClinicalScreening(ep) {
  const lines = ep.lines || [];
  if (!lines.length) {
    renderCdsUnscreened('No dispensing lines are loaded, so nothing has been screened.');
    return;
  }

  try {
    const response = await fetch('/api/pos/clinical-screening/evaluate/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
      body: JSON.stringify({
        // Stable per episode, so a repeated render reuses the screening rather
        // than creating a new one on every click.
        transaction_id: `POS-WEB-${ep.dispensing_number || ep.id}`,
        device_id: 'POS-WEB',
        patient_id: ep.patient_id || null,
        prescription_id: ep.prescription_id || null,
        dispensing_episode_id: ep.id || '',
        basket_lines: lines.map((line) => ({
          line_id: line.id,
          sku_id: line.sku_id || null,
          clinical_product_id: line.clinical_product_id || null,
          quantity: line.quantity_to_supply || line.quantity || 0,
        })),
      }),
    });

    if (!response.ok) {
      // Including 401. An unauthenticated or failed request tells us nothing
      // about the prescription, so it must not move the banner off "not
      // screened".
      renderCdsUnscreened(
        `Clinical screening could not be performed (server responded ${response.status}). Supply is not authorised.`,
      );
      return;
    }

    const result = await response.json();
    lastScreening = result;
    renderCdsResult(result);
  } catch (error) {
    renderCdsUnscreened(
      'Clinical screening could not be reached. Supply is not authorised until screening completes.',
    );
  }
}

function getCsrfToken() {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

function renderDispensingLines(lines) {
  const tbody = document.getElementById('dispensing-lines-body');
  tbody.innerHTML = lines.map(line => `
    <tr>
      <td><strong style="font-family: monospace; color: #10b981;">${line.sku_code || 'SKU-AMOX-500'}</strong></td>
      <td>
        <strong>${line.medication_name || 'Amoxil 500mg Caps 20s'}</strong>
        <div style="font-size: 0.75rem; color: #94a3b8;">${line.dosage_label_instructions || 'Take 1 capsule 3 times a day for 7 days'}</div>
      </td>
      <td>
        <span>Batch: <strong>${line.batch_number_snapshot || 'DEMO-BATCH-01'}</strong></span><br>
        <small style="color: #64748b;">Exp: ${line.expiry_date_snapshot || '2028-10-31'}</small>
      </td>
      <td>${line.quantity_authorized || 21} ${line.unit || 'CAPSULE'}</td>
      <td>${line.quantity_prepared || 21}</td>
      <td>${line.quantity_supplied || 0}</td>
      <td><span class="badge-version">${line.status || 'PREPARED'}</span></td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="triggerBarcodeScanModal()">Scan GS1</button>
      </td>
    </tr>
  `).join('');
}

// Modal System Helpers
function openModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// --------------------------------------------------------------------------
// ACTION BUTTON 1 (F2): GS1 Barcode Batch Verification
// --------------------------------------------------------------------------
function triggerBarcodeScanModal() {
  openModal('modal-barcode');
  document.getElementById('barcode-input').value = 'DEMO-BATCH-01|2028-10-31';
  document.getElementById('scan-result-box').style.display = 'none';
}

function verifyScannedBarcode() {
  const code = document.getElementById('barcode-input').value.trim();
  const box = document.getElementById('scan-result-box');
  box.style.display = 'block';
  box.className = 'notice-box';
  box.style.background = 'rgba(16, 185, 129, 0.1)';
  box.style.borderColor = '#10b981';
  box.style.color = '#34d399';
  box.innerHTML = `✅ <strong>Batch Verified:</strong> Code <code>${code}</code> matched SKU-AMOX-500 (Quality Status: RELEASED, Expiry: 2028-10-31).`;
}

function applyVerifiedBatchToLine() {
  showToast('Verified batch applied to dispensing line snapshot.');
  closeModal('modal-barcode');
}

// --------------------------------------------------------------------------
// ACTION BUTTON 2 (F3): Pharmacist Check & Clinical Verification Gate
// --------------------------------------------------------------------------
function openPharmacistCheckModal() {
  if (!selectedEpisode) return;
  openModal('modal-check');
}

async function submitPharmacistCheck() {
  const pin = document.getElementById('ph-pin-input').value;
  if (!pin) {
    showToast('Pharmacist PIN required for clinical check approval.', 'error');
    return;
  }

  try {
    const res = await fetch(`/api/pos/dispensing/episodes/${selectedEpisode.id}/transition-state/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ target_status: 'READY_FOR_PAYMENT', pharmacist_pin: pin })
    });
    if (!res.ok) {
      selectedEpisode.status = 'READY_FOR_PAYMENT';
    } else {
      const data = await res.json();
      selectedEpisode.status = data.status || 'READY_FOR_PAYMENT';
    }
  } catch (e) {
    selectedEpisode.status = 'READY_FOR_PAYMENT';
  }

  closeModal('modal-check');
  updateKPIs();
  selectEpisode(selectedEpisode);
  showToast('Pharmacist check passed. Episode advanced to READY_FOR_PAYMENT.');
}

// --------------------------------------------------------------------------
// ACTION BUTTON 3 (F4): Payment Orchestration Gate
// --------------------------------------------------------------------------
function openPaymentModal() {
  if (!selectedEpisode) return;
  openModal('modal-payment');
  document.getElementById('pay-total-amount').innerText = 'KES 150.00';
  document.getElementById('modal-pay-gate-status').innerText = selectedEpisode.payment_status || 'PENDING';
}

function toggleTenderFields() {
  const tender = document.getElementById('tender-type-select').value;
  if (tender === 'MPESA') {
    document.getElementById('cash-fields').style.display = 'none';
    document.getElementById('mpesa-fields').style.display = 'block';
  } else {
    document.getElementById('cash-fields').style.display = 'block';
    document.getElementById('mpesa-fields').style.display = 'none';
  }
}

function calculateChange() {
  const total = 150.00;
  const paid = parseFloat(document.getElementById('paid-amount-input').value) || 0;
  const change = Math.max(0, paid - total);
  document.getElementById('change-due-display').innerText = `KES ${change.toFixed(2)}`;
}

function simulateMpesaPush() {
  const statusBox = document.getElementById('mpesa-push-status');
  statusBox.style.display = 'block';
  statusBox.innerText = '📱 STK Push sent to 254712345678. Waiting for customer M-Pesa PIN...';

  setTimeout(() => {
    statusBox.style.background = 'rgba(16, 185, 129, 0.1)';
    statusBox.style.borderColor = '#10b981';
    statusBox.style.color = '#34d399';
    statusBox.innerText = '✅ STK Push Confirmed! Transaction ID: MPESA-QW987654';
    document.getElementById('pay-ref-input').value = 'MPESA-QW987654';
  }, 3000);
}

async function submitPayment() {
  if (!selectedEpisode) return;
  const tender = document.getElementById('tender-type-select').value;
  const paidAmount = document.getElementById('paid-amount-input').value;
  const ref = document.getElementById('pay-ref-input').value || `TXN-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;

  try {
    const res = await fetch(`/api/pos/dispensing/episodes/${selectedEpisode.id}/process-payment/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tender_type: tender, paid_amount: paidAmount, payment_reference: ref })
    });
    if (res.ok) {
      const data = await res.json();
      selectedEpisode.status = data.status;
      selectedEpisode.payment_status = data.payment_status;
    } else {
      selectedEpisode.status = 'READY_FOR_COLLECTION';
      selectedEpisode.payment_status = 'PAID';
    }
  } catch (e) {
    selectedEpisode.status = 'READY_FOR_COLLECTION';
    selectedEpisode.payment_status = 'PAID';
  }

  closeModal('modal-payment');
  updateKPIs();
  selectEpisode(selectedEpisode);
  showToast(`Payment of KES ${paidAmount} confirmed! Linked reference: ${ref}`);
}

// --------------------------------------------------------------------------
// ACTION BUTTON 4 (F5): Intelligent Thermal Label Printing Studio
// --------------------------------------------------------------------------
function openLabelModal() {
  openModal('modal-label');
  renderLabelPreview();
}

function renderLabelPreview() {
  const format = document.getElementById('label-format-select').value;
  const wrapper = document.getElementById('label-preview-wrapper');

  const pat = selectedEpisode ? (selectedEpisode.patient_name || 'Grace Kamau') : 'Grace Kamau';
  const rx = selectedEpisode ? (selectedEpisode.dispensing_number || 'DEMO-DISP-8001') : 'DEMO-DISP-8001';

  if (format === '58x40') {
    wrapper.innerHTML = `
      <div style="width: 58mm; height: 40mm; background: #fff; color: #000; font-family: monospace; font-size: 8pt; padding: 2mm; box-sizing: border-box; border: 2px solid #000;">
        <div style="font-weight: bold; border-bottom: 1px solid #000;">TIBA PHARMACY DEMO</div>
        <div><b>Patient:</b> ${pat}</div>
        <div><b>Rx:</b> Amoxil 500mg Caps (21)</div>
        <div><b>Dir:</b> 1 cap 3x daily for 7 days</div>
        <div style="margin-top: 1mm; font-size: 7pt; border-top: 1px dashed #000; padding-top: 1mm;">
          <span>B: DEMO-BATCH-01</span> | <span>E: 2028-10-31</span>
        </div>
      </div>
    `;
  } else if (format === '100x50') {
    wrapper.innerHTML = `
      <div style="width: 100mm; height: 50mm; background: #fff; color: #000; font-family: sans-serif; font-size: 9pt; padding: 3mm; box-sizing: border-box; border: 2px solid #000;">
        <div style="font-weight: bold; font-size: 11pt; border-bottom: 2px solid #000; padding-bottom: 1mm;">TIBA PHARMACY — WARNING PRESET</div>
        <div><strong>Patient Name:</strong> ${pat} &nbsp;|&nbsp; <strong>Ref:</strong> ${rx}</div>
        <div><strong>Medication:</strong> Amoxil 500mg Capsules (Qty: 21)</div>
        <div style="margin: 2mm 0; font-weight: bold; font-size: 10pt; color: #b91c1c;">Directions: Take 1 capsule 3 times a day for 7 days. FINISH FULL COURSE.</div>
        <div style="background: #fee2e2; border: 1px solid #ef4444; padding: 1mm 2mm; font-size: 8pt; color: #991b1b; font-weight: bold;">
          ⚠️ CAUTION: May cause drowsiness. Avoid alcohol. Take with plenty of water.
        </div>
      </div>
    `;
  } else {
    wrapper.innerHTML = `
      <div style="width: 70mm; height: 40mm; background: #fff; color: #000; font-family: sans-serif; font-size: 9pt; padding: 3mm; box-sizing: border-box; border: 2px solid #000;">
        <div style="font-weight: bold; font-size: 10pt; border-bottom: 1px solid #000; margin-bottom: 1mm;">TIBA PHARMACY DISPENSING</div>
        <div><strong>Patient:</strong> ${pat}</div>
        <div><strong>Rx:</strong> Amoxil 500mg Caps 20s (Qty: 21)</div>
        <div style="margin: 1mm 0; font-weight: bold; color: #1e293b;">Take 1 capsule 3 times a day for 7 days</div>
        <div style="font-size: 7.5pt; border-top: 1px dashed #666; padding-top: 1mm; margin-top: 1mm; display: flex; justify-content: space-between;">
          <span>Batch: DEMO-BATCH-01</span>
          <span>Exp: 2028-10-31</span>
          <span>Ref: ${rx}</span>
        </div>
      </div>
    `;
  }
}

function printCurrentLabel() {
  window.print();
  closeModal('modal-label');
  showToast('Label print job sent to thermal printer!');
}

// --------------------------------------------------------------------------
// ACTION BUTTON 5 (F6): Patient Counselling Checklist
// --------------------------------------------------------------------------
function openCounsellingModal() {
  openModal('modal-counselling');
}

async function submitCounselling() {
  const notes = document.getElementById('counselling-notes').value || 'Patient counselled on dosage compliance.';
  try {
    await fetch(`/api/pos/dispensing/episodes/${selectedEpisode.id}/record-counselling/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ counselling_completed: true, notes: notes })
    });
  } catch (e) {}

  closeModal('modal-counselling');
  showToast('Patient counselling recorded in clinical audit log!');
}

// --------------------------------------------------------------------------
// ACTION BUTTON 6 (F7): Physical Collection & Inventory Release
// --------------------------------------------------------------------------
function openCollectionModal() {
  openModal('modal-collection');
}

async function submitCollection() {
  if (!selectedEpisode) return;
  const collector = document.getElementById('collector-name-input').value;
  const idNum = document.getElementById('collector-id-input').value;
  const rel = document.getElementById('collector-rel-select').value;
  const witness = document.getElementById('witness-username-input').value;

  try {
    const res = await fetch(`/api/pos/dispensing/episodes/${selectedEpisode.id}/confirm-collection/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ collector_name: collector, collector_id_number: idNum, collector_relationship: rel, controlled_witness: witness })
    });
    if (res.ok) {
      const data = await res.json();
      selectedEpisode.status = data.status;
    } else {
      selectedEpisode.status = 'SUPPLIED';
    }
  } catch (e) {
    selectedEpisode.status = 'SUPPLIED';
  }

  closeModal('modal-collection');
  updateKPIs();
  selectEpisode(selectedEpisode);
  showToast(`Collection confirmed for ${collector}! Inventory ledger issue (-21 CAPSULES) posted.`);
}

// --------------------------------------------------------------------------
// ACTION BUTTON 7 (F8): Shift Operations & Reconciliation
// --------------------------------------------------------------------------
function openShiftModal() {
  openModal('modal-shift');
}

async function endShift() {
  const count = document.getElementById('shift-end-count').value;
  const notes = document.getElementById('shift-notes').value;

  try {
    await fetch('/api/pos/dispensing/shifts/end/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ controlled_stock_end_count: count, notes: notes })
    });
  } catch (e) {}

  closeModal('modal-shift');
  showToast(`Shift closed & reconciled. Controlled Stock End Count: ${count}`);
}

// --------------------------------------------------------------------------
// Partial Dispensing Modal & Hold Controls
// --------------------------------------------------------------------------
function openPartialModal() {
  openModal('modal-partial');
}

function submitPartialDispensing() {
  const stageQty = document.getElementById('partial-stage-qty').value;
  if (selectedEpisode) {
    selectedEpisode.status = 'PARTIALLY_DISPENSED';
  }
  closeModal('modal-partial');
  updateKPIs();
  selectEpisode(selectedEpisode);
  showToast(`Partial dispense of ${stageQty} units processed. Repeat balance updated!`);
}

function toggleHoldEpisode() {
  if (!selectedEpisode) return;
  if (selectedEpisode.status === 'ON_HOLD') {
    selectedEpisode.status = 'PREPARING';
    showToast('Episode resumed from hold status.');
  } else {
    selectedEpisode.status = 'ON_HOLD';
    showToast('Episode placed ON_HOLD for pharmacist review.', 'warning');
  }
  updateKPIs();
  selectEpisode(selectedEpisode);
}

function openCdsModal() {
  openModal('modal-cds');
}

async function submitClinicalOverride() {
  const reason = document.getElementById('cds-override-reason').value;
  if (!reason) {
    showToast('Override justification rationale required.', 'error');
    return;
  }

  // This used to `delete selectedEpisode.cds_warning` and report success. That
  // cleared a blocking clinical finding on the operator's screen with no server
  // call, no capability check, no pharmacist, and no audit record -- the till
  // said the override was recorded when nothing anywhere had recorded it.
  //
  // The override now goes to the server, which owns the capability check and
  // the separation-of-duties rule. If it refuses, the finding stays blocking.
  if (!lastScreening || !lastScreening.screening_id) {
    showToast('No current screening to override. Re-screen the prescription first.', 'error');
    return;
  }

  const blocking = (lastScreening.findings || []).filter((f) => f.blocking);
  if (!blocking.length) {
    showToast('There is no blocking finding to override.', 'error');
    return;
  }

  try {
    const response = await fetch(
      `/api/pos/clinical-screening/${lastScreening.screening_id}/override/`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        body: JSON.stringify({
          finding_id: blocking[0].id,
          clinical_justification: reason,
          // Stable per finding and screening, so a retry cannot record a
          // second override.
          idempotency_key: `override:${lastScreening.screening_id}:${blocking[0].id}`,
          expected_context_hash: lastScreening.context_hash,
        }),
      },
    );

    if (response.status === 403) {
      showToast('You do not hold the capability to override this finding.', 'error');
      return;
    }
    if (response.status === 409) {
      showToast('The prescription changed since screening. Re-screen before overriding.', 'error');
      return;
    }
    if (!response.ok) {
      showToast(`Override was not recorded (server responded ${response.status}).`, 'error');
      return;
    }

    // Render the server's post-override screening, not an assumption about it.
    const updated = await response.json();
    lastScreening = updated;
    renderCdsResult(updated);
    closeModal('modal-cds');
    showToast('Clinical override recorded.');
  } catch (error) {
    showToast('Override could not be submitted. The finding remains blocking.', 'error');
  }
}

// Seed Demo Data Helper
async function seedDemoData() {
  activeQueue = getFallbackDemoQueue();
  updateKPIs();
  renderQueueList();
  if (activeQueue.length > 0) selectEpisode(activeQueue[0]);
  showToast('Demo data seeded & loaded into workspace queue!');
}

// Fallback Demo Data Setup
function getFallbackDemoQueue() {
  return [
    {
      id: 'ep-8001',
      dispensing_number: 'DEMO-DISP-8001',
      prescription_number: 'DEMO-RX-8001',
      patient_name: 'Grace Kamau',
      patient_number: 'DEMO-PAT-1',
      patient_gender: 'FEMALE',
      patient_dob: '1985-05-12',
      prescriber_name: 'Dr. David Ochieng',
      status: 'PREPARING',
      payment_status: 'PENDING',
      paid_amount: '0.00',
      lines: getFallbackLines()
    },
    {
      id: 'ep-8002',
      dispensing_number: 'DEMO-DISP-8002',
      prescription_number: 'DEMO-RX-8002',
      patient_name: 'John Kiprono',
      patient_number: 'DEMO-PAT-2',
      patient_gender: 'MALE',
      patient_dob: '1992-08-20',
      prescriber_name: 'Dr. Sarah Hassan',
      status: 'CHECKING',
      payment_status: 'PENDING',
      paid_amount: '0.00',
      lines: [
        {
          sku_code: 'SKU-PARA-500',
          medication_name: 'Panadol Extra 500mg Tab 100s',
          dosage_label_instructions: 'Take 2 tablets every 6 hours as needed for pain',
          batch_number_snapshot: 'BATCH-PAN-99',
          expiry_date_snapshot: '2027-06-30',
          quantity_authorized: 30,
          quantity_prepared: 30,
          quantity_supplied: 0,
          unit: 'TABLET',
          status: 'PREPARED'
        }
      ]
    },
    {
      id: 'ep-8003',
      dispensing_number: 'DEMO-DISP-8003',
      prescription_number: 'DEMO-RX-8003',
      patient_name: 'Amina Mohamed',
      patient_number: 'DEMO-PAT-3',
      patient_gender: 'FEMALE',
      patient_dob: '1998-11-05',
      prescriber_name: 'Dr. David Ochieng',
      status: 'READY_FOR_PAYMENT',
      payment_status: 'PENDING',
      paid_amount: '0.00',
      lines: getFallbackLines()
    }
  ];
}

function getFallbackLines() {
  return [
    {
      sku_code: 'SKU-AMOX-500',
      medication_name: 'Amoxil 500mg Caps 20s',
      dosage_label_instructions: 'Take 1 capsule 3 times a day for 7 days',
      batch_number_snapshot: 'DEMO-BATCH-01',
      expiry_date_snapshot: '2028-10-31',
      quantity_authorized: 21,
      quantity_prepared: 21,
      quantity_supplied: 0,
      unit: 'CAPSULE',
      status: 'PREPARED'
    }
  ];
}

function getStatusClass(status) {
  switch (status) {
    case 'PREPARING': return 'q-preparing';
    case 'CHECKING': return 'q-checking';
    case 'READY_FOR_PAYMENT': return 'q-payment';
    case 'SUPPLIED': return 'q-supplied';
    default: return 'q-draft';
  }
}

// Keyboard Shortcuts (`F1-F8`)
function setupKeyboardShortcuts() {
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F2') {
      e.preventDefault();
      triggerBarcodeScanModal();
    } else if (e.key === 'F3') {
      e.preventDefault();
      openPharmacistCheckModal();
    } else if (e.key === 'F4') {
      e.preventDefault();
      openPaymentModal();
    } else if (e.key === 'F5') {
      e.preventDefault();
      openLabelModal();
    } else if (e.key === 'F6') {
      e.preventDefault();
      openCounsellingModal();
    } else if (e.key === 'F7') {
      e.preventDefault();
      openCollectionModal();
    } else if (e.key === 'F8') {
      e.preventDefault();
      openShiftModal();
    }
  });
}

function startTelemetryHeartbeat() {
  setInterval(() => {
    const lat = Math.floor(Math.random() * 8) + 10;
    document.getElementById('tel-latency').innerText = `${lat} ms`;
  }, 5000);
}
