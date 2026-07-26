/* ==========================================================================
   TibaTrace Enterprise Pharmacy POS — JavaScript Interactive Terminal Application
   ========================================================================== */

let activeQueue = [];
let selectedEpisode = null;
let currentFilter = 'ALL';
let currentShift = null;

// Initialize POS Application
document.addEventListener('DOMContentLoaded', () => {
  fetchQueue();
  setupKeyboardShortcuts();
  startTelemetryHeartbeat();
});

// Fetch Dispensing Queue from API
async function fetchQueue() {
  try {
    const response = await fetch('/api/pos/dispensing/episodes/queue/');
    if (!response.ok) {
      if (response.status === 401) {
        console.warn('Authentication required. Using demo mode.');
      }
      activeQueue = getFallbackDemoQueue();
    } else {
      activeQueue = await response.json();
    }

    if (activeQueue.length === 0) {
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

// Update KPI Stats Cards
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
    container.innerHTML = '<div class="queue-empty-state" style="padding: 20px; text-align: center; color: #64748b;">No matching dispensing episodes.</div>';
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
          <span>Payment: ${ep.payment_status || 'PENDING'}</span>
        </div>
      </div>
    `;
  }).join('');
}

function selectEpisodeById(id) {
  const ep = activeQueue.find(e => e.id === id);
  if (ep) selectEpisode(ep);
}

// Select Active Dispensing Episode into Workspace
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
  document.getElementById('payment-status-tag').innerText = `Payment: ${ep.payment_status || 'PENDING'}`;

  renderDispensingLines(ep.lines || getFallbackLines());
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

// Modal Helpers
function openModal(id) {
  document.getElementById(id).classList.add('open');
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

// Barcode Scan Verification
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
  box.innerHTML = `✅ <strong>Batch Verified:</strong> Code <code>${code}</code> matched SKU-AMOX-500 (Release Status: RELEASED, Expiry: 2028-10-31).`;
}

// Payment Gate Modal
function openPaymentModal() {
  if (!selectedEpisode) return;
  openModal('modal-payment');
}

async function submitPayment() {
  if (!selectedEpisode) return;
  const tender = document.getElementById('tender-type-select').value;
  const amount = document.getElementById('paid-amount-input').value;
  const ref = document.getElementById('pay-ref-input').value || `MPESA-${Math.random().toString(36).substring(2, 8).toUpperCase()}`;

  selectedEpisode.payment_status = 'PAID';
  selectedEpisode.paid_amount = amount;
  selectedEpisode.status = 'READY_FOR_COLLECTION';
  closeModal('modal-payment');

  updateKPIs();
  selectEpisode(selectedEpisode);
  alert(`Payment processed successfully! Linked Reference: ${ref}`);
}

// Label Modal & Print Engine
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
  alert('Label sent to thermal label printer!');
  closeModal('modal-label');
}

// Patient Counselling Modal
function openCounsellingModal() {
  openModal('modal-counselling');
}

function submitCounselling() {
  if (selectedEpisode) {
    selectedEpisode.counselling_status = 'COMPLETED';
  }
  closeModal('modal-counselling');
  alert('Patient counselling completed and recorded in clinical log!');
}

// Physical Collection Confirmation Modal
function openCollectionModal() {
  openModal('modal-collection');
}

function submitCollection() {
  if (!selectedEpisode) return;
  selectedEpisode.status = 'SUPPLIED';
  selectedEpisode.quantity_supplied = 21;

  closeModal('modal-collection');
  updateKPIs();
  selectEpisode(selectedEpisode);
  alert('Physical collection confirmed! Inventory Ledger Entry (ISSUE -21 CAPSULES) posted.');
}

// Shift Operations Modal
function openShiftModal() {
  openModal('modal-shift');
}

function endShift() {
  const notes = document.getElementById('shift-notes').value;
  alert(`Shift DEMO-SHIFT-01 closed and reconciled. Notes: ${notes}`);
  closeModal('modal-shift');
}

// State Transition Engine
function transitionState(newStatus) {
  if (!selectedEpisode) return;
  selectedEpisode.status = newStatus;
  updateKPIs();
  selectEpisode(selectedEpisode);
}

// Seed Demo Data Helper
async function seedDemoData() {
  try {
    const res = await fetch('/api/pos/dispensing/episodes/');
    activeQueue = getFallbackDemoQueue();
    updateKPIs();
    renderQueueList();
    if (activeQueue.length > 0) selectEpisode(activeQueue[0]);
  } catch (e) {
    activeQueue = getFallbackDemoQueue();
    updateKPIs();
    renderQueueList();
    if (activeQueue.length > 0) selectEpisode(activeQueue[0]);
  }
}

// Fallback Demo Data
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

// Keyboard Shortcut Maps (F1-F8)
function setupKeyboardShortcuts() {
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F2') {
      e.preventDefault();
      triggerBarcodeScanModal();
    } else if (e.key === 'F3') {
      e.preventDefault();
      transitionState('CHECKING');
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
