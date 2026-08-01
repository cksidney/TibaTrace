/**
 * TibaTrace POS terminal shell.
 *
 * Loads the authenticated dispensing queue, lets an operator drill into
 * episodes, and drives the workspace / KPI / modal surface declared in
 * templates/pos/pos.html.
 */
(function () {
  "use strict";

  const QUEUE_URL = "/api/pos/dispensing/episodes/queue/";
  const EPISODE_URL = (id) => `/api/pos/dispensing/episodes/${encodeURIComponent(id)}/`;
  const SHIFT_URL = "/api/pos/dispensing/shifts/";
  const DEVICE_URL = "/api/pos/dispensing/devices/";
  const REGISTER_URL = "/api/pos/shift/registers/";
  const SESSION_URL = "/api/identity/session/";
  const DEMO_SEED_URL = "/api/pos/demo-seed/";
  const CDS_EVALUATE_URL = "/api/pos/clinical-screening/evaluate/";
  const CDS_SCREENING_URL = (id) => `/api/pos/clinical-screening/${encodeURIComponent(id)}/`;
  const CDS_OVERRIDES_URL = "/api/pos/clinical-screening/overrides/";
  const CDS_OVERRIDE_URL = (id) => `/api/pos/clinical-screening/overrides/${encodeURIComponent(id)}/`;

  const TERMINAL_STATUSES = ["SUPPLIED", "CLOSED", "CANCELLED", "REJECTED"];

  const state = {
    queue: [],
    filter: "ALL",
    search: "",
    selectedId: null,
    episode: null,
    shift: null,
    device: null,
    verifiedBatch: null,
    user: null,
    screening: null,
    cdsBusy: false,
    selectedFindingId: null,
  };

  function csrfToken() {
    const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function api(url, options = {}) {
    const headers = Object.assign(
      {
        Accept: "application/json",
        "X-POS-Client-Platform": "WEB",
        "X-POS-Client-Version": "1.0.0",
        "X-POS-Client-Build": "1",
      },
      options.headers || {},
    );
    if (options.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    if (options.method && options.method !== "GET") {
      headers["X-CSRFToken"] = csrfToken();
    }
    const response = await fetch(url, Object.assign({}, options, {
      credentials: "include",
      headers,
    }));
    if (response.status === 401 || response.status === 403) {
      updateSessionUi(null);
      if (url.indexOf("/session/") === -1) {
        showLogin(
          response.status === 403
            ? "Sign in with a pharmacy operator (demo_dispensing_rph) to load seeded till data."
            : "Sign in to use the dispensing terminal.",
        );
      }
      const err = new Error("Authentication required");
      err.status = response.status;
      throw err;
    }
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = await response.json();
        if (typeof body.detail === "string") detail = body.detail;
        else if (Array.isArray(body.detail)) detail = body.detail.map((d) => (d && d.string) || d).join("; ");
        else if (Array.isArray(body.non_field_errors)) detail = body.non_field_errors.join("; ");
        else if (body && typeof body === "object") {
          const parts = Object.keys(body).map((k) => {
            const v = body[k];
            return `${k}: ${Array.isArray(v) ? v.join(", ") : v}`;
          });
          if (parts.length) detail = parts.join("; ");
        }
      } catch (_) { /* keep status text */ }
      const err = new Error(detail);
      err.status = response.status;
      err.cdsRelated = /clinical|screening|CDS|override|finding|safe_to_proceed|context/i.test(detail);
      throw err;
    }
    if (response.status === 204) return null;
    const type = response.headers.get("Content-Type") || "";
    return type.includes("application/json") ? response.json() : response.text();
  }

  function updateSessionUi(user) {
    state.user = user || null;
    const area = document.getElementById("pos-session-area");
    const label = document.getElementById("pos-session-label");
    const signIn = document.getElementById("btn-pos-signin");
    const signOut = document.getElementById("btn-pos-signout");
    const signedIn = Boolean(user);
    if (area) area.classList.toggle("is-signed-in", signedIn);
    if (label) {
      label.textContent = signedIn
        ? `${user.display_name || user.username}${user.tenant_name ? " · " + user.tenant_name : ""}`
        : "Not signed in";
    }
    if (signIn) {
      signIn.hidden = signedIn;
      signIn.style.display = signedIn ? "none" : "";
    }
    if (signOut) {
      signOut.hidden = !signedIn;
      signOut.style.display = signedIn ? "" : "none";
    }
  }

  function ensureLoginOverlay() {
    let overlay = document.getElementById("pos-login-overlay");
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "pos-login-overlay";
    overlay.className = "modal-overlay";
    overlay.innerHTML = `
      <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="pos-login-title">
        <div class="modal-header"><h3 id="pos-login-title">POS Terminal Sign-in</h3></div>
        <div class="modal-body">
          <p id="pos-login-message" style="margin-bottom:12px;color:#94a3b8;"></p>
          <div class="form-group"><label for="pos-login-user">Username</label><input id="pos-login-user" class="form-control" value="demo_dispensing_rph" autocomplete="username"></div>
          <div class="form-group"><label for="pos-login-pass">Password</label><input id="pos-login-pass" type="password" class="form-control" autocomplete="current-password"></div>
          <p id="pos-login-error" style="display:none;color:#f87171;margin-top:8px;"></p>
          <p style="margin-top:10px;font-size:12px;color:#64748b;">Demo operator loads the seeded dispensing queue for this till.</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" type="button" id="pos-login-cancel">Cancel</button>
          <button class="btn btn-success" type="button" id="pos-login-submit">Sign in</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    document.getElementById("pos-login-submit").addEventListener("click", submitLogin);
    document.getElementById("pos-login-cancel").addEventListener("click", () => hideLogin());
    document.getElementById("pos-login-pass").addEventListener("keydown", (e) => {
      if (e.key === "Enter") submitLogin();
    });
    return overlay;
  }

  function showLogin(message) {
    const overlay = ensureLoginOverlay();
    const msg = document.getElementById("pos-login-message");
    if (msg) {
      msg.textContent = message || "Sign in to load the dispensing queue and episode details.";
    }
    const err = document.getElementById("pos-login-error");
    if (err) err.style.display = "none";
    overlay.classList.add("open");
  }

  function hideLogin() {
    const overlay = document.getElementById("pos-login-overlay");
    if (overlay) overlay.classList.remove("open");
  }

  window.openPosSignIn = function openPosSignIn() {
    showLogin("Sign in with a pharmacy operator to view seeded till episodes.");
  };

  window.signOutPos = async function signOutPos() {
    try {
      await api(SESSION_URL, { method: "DELETE" });
    } catch (_) { /* still clear local UI */ }
    state.queue = [];
    state.selectedId = null;
    state.episode = null;
    updateSessionUi(null);
    renderKpis();
    renderQueue();
    renderEpisode(null);
    const container = document.getElementById("queue-list-container");
    if (container) {
      container.innerHTML = `<div class="queue-empty-state">Signed out. Use <strong>Sign in</strong> to load the till queue.</div>`;
    }
    showLogin("Signed out. Sign in again to continue.");
  };

  async function submitLogin() {
    const username = document.getElementById("pos-login-user").value.trim();
    const password = document.getElementById("pos-login-pass").value;
    const errorEl = document.getElementById("pos-login-error");
    errorEl.style.display = "none";
    try {
      await fetch(SESSION_URL, { credentials: "include", headers: { Accept: "application/json" } });
      const response = await fetch(SESSION_URL, {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({ username, password }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body.detail || `Sign-in failed (${response.status})`);
      }
      updateSessionUi(body.user || { username });
      hideLogin();
      await bootstrap();
    } catch (err) {
      errorEl.textContent = err.message || "Sign-in failed.";
      errorEl.style.display = "block";
    }
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value == null || value === "" ? "—" : String(value);
  }

  /** Fixed 2dp without Number()/toFixed float risk. */
  function formatDecimal(value, places) {
    places = places == null ? 2 : places;
    if (value == null || value === "") return places ? "0." + Array(places + 1).join("0") : "0";
    const text = String(value).trim();
    if (!/^-?\d+(\.\d+)?$/.test(text)) return places ? "0." + Array(places + 1).join("0") : "0";
    const negative = text.charAt(0) === "-";
    const raw = negative ? text.slice(1) : text;
    const parts = raw.split(".");
    let whole = parts[0].replace(/^0+(?=\d)/, "") || "0";
    let fraction = parts[1] || "";
    const padded = (fraction + Array(places + 2).join("0")).slice(0, places + 1);
    let keep = padded.slice(0, places);
    const next = padded.charAt(places);
    if (next >= "5") {
      const digits = (whole + keep).split("").map(function (d) { return Number(d); });
      let i = digits.length - 1;
      digits[i] += 1;
      while (i > 0 && digits[i] === 10) {
        digits[i] = 0;
        i -= 1;
        digits[i] += 1;
      }
      if (digits[0] === 10) {
        digits[0] = 0;
        digits.unshift(1);
      }
      const joined = digits.join("");
      const cut = joined.length - places;
      whole = joined.slice(0, cut) || "0";
      keep = places ? joined.slice(cut) : "";
    } else {
      keep = (keep + Array(places + 1).join("0")).slice(0, places);
    }
    const body = places > 0 ? whole + "." + keep : whole;
    return (negative ? "-" : "") + body;
  }

  function formatMoney(value, currency) {
    currency = currency || "KES";
    const amount = formatDecimal(value, 2);
    const negative = amount.charAt(0) === "-";
    const unsigned = negative ? amount.slice(1) : amount;
    const bits = unsigned.split(".");
    const grouped = bits[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return currency + " " + (negative ? "-" : "") + grouped + "." + (bits[1] || "00");
  }

  function statusTone(status) {
    const map = {
      PREPARING: "#38bdf8",
      CHECKING: "#fbbf24",
      READY_FOR_PAYMENT: "#a78bfa",
      PAID: "#34d399",
      READY_FOR_COLLECTION: "#34d399",
      READY_FOR_SUPPLY: "#34d399",
      PARTIALLY_SUPPLIED: "#fb923c",
      SUPPLIED: "#94a3b8",
      ON_HOLD: "#f87171",
      CLOSED: "#64748b",
    };
    return map[status] || "#94a3b8";
  }

  function episodeSearchText(episode) {
    const lineText = (episode.lines || [])
      .map((line) => [line.dosage_label_instructions, line.batch_number_snapshot, line.status].join(" "))
      .join(" ");
    return [
      episode.dispensing_number,
      episode.patient_name,
      episode.patient_number,
      episode.prescription_number,
      episode.prescriber_name,
      episode.status,
      episode.payment_state,
      episode.insurer_name,
      episode.scheme_name,
      episode.membership_number,
      episode.notes,
      lineText,
    ].join(" ").toLowerCase();
  }

  function isControlledEpisode(episode) {
    if (episode.controlled_authority_checked) return true;
    const text = episodeSearchText(episode);
    return (
      text.includes("controlled") ||
      text.includes("schedule ii") ||
      text.includes("schedule 2") ||
      text.includes("morphine") ||
      text.includes("cd register")
    );
  }

  function matchesKpiFilter(episode) {
    if (state.filter === "ALL") return true;
    if (state.filter === "ACTIVE") {
      return !TERMINAL_STATUSES.includes(episode.status);
    }
    if (state.filter === "CONTROLLED") {
      return isControlledEpisode(episode);
    }
    return episode.status === state.filter;
  }

  function filteredQueue() {
    const needle = state.search.trim().toLowerCase();
    return state.queue.filter((episode) => {
      if (!matchesKpiFilter(episode)) return false;
      if (!needle) return true;
      return episodeSearchText(episode).includes(needle);
    });
  }

  function syncSearchInputs(value) {
    state.search = value || "";
    ["queue-search-input", "episode-search", "episode-search-empty"].forEach((id) => {
      const el = document.getElementById(id);
      if (el && el.value !== state.search) el.value = state.search;
    });
  }

  function applySearchFilter(value) {
    syncSearchInputs(value);
    renderQueue();
    const rows = filteredQueue();
    if (state.selectedId && !rows.some((e) => e.id === state.selectedId)) {
      const nextId = preferredEpisodeId();
      if (nextId) selectEpisode(nextId);
      else {
        state.selectedId = null;
        renderEpisode(null);
        syncEpisodePickers();
      }
    } else {
      syncEpisodePickers();
    }
  }

  window.filterEpisodeSearch = function filterEpisodeSearch(value) {
    applySearchFilter(value);
  };

  function renderKpis() {
    const counts = {
      queue: state.queue.filter((e) => !TERMINAL_STATUSES.includes(e.status)).length,
      checking: state.queue.filter((e) => e.status === "CHECKING").length,
      payment: state.queue.filter((e) => e.status === "READY_FOR_PAYMENT").length,
      supplied: state.queue.filter((e) => e.status === "SUPPLIED").length,
    };
    setText("kpi-queue-count", counts.queue);
    setText("kpi-checking-count", counts.checking);
    setText("kpi-payment-count", counts.payment);
    setText("kpi-supplied-count", counts.supplied);
    if (state.shift && state.shift.controlled_stock_start_count != null) {
      setText("kpi-controlled-count", state.shift.controlled_stock_start_count);
    }
    document.querySelectorAll(".kpi-card[data-kpi]").forEach((card) => {
      card.classList.toggle("is-active", card.getAttribute("data-kpi") === state.filter);
    });
  }

  function syncFilterTabs() {
    const tabFilter =
      state.filter === "ACTIVE" || state.filter === "CONTROLLED" ? "ALL" : state.filter;
    document.querySelectorAll(".filter-tabs .tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-filter") === tabFilter);
    });
  }

  function applyQueueFilter(filter) {
    state.filter = filter;
    syncFilterTabs();
    renderKpis();
    renderQueue();
    const nextId = preferredEpisodeId();
    if (nextId && nextId !== state.selectedId) {
      selectEpisode(nextId);
    } else if (!nextId) {
      state.selectedId = null;
      renderEpisode(null);
      syncEpisodePickers();
    }
    const queuePanel = document.querySelector(".queue-panel");
    if (queuePanel) queuePanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function renderQueue() {
    const container = document.getElementById("queue-list-container");
    if (!container) return;
    const rows = filteredQueue();
    if (!rows.length) {
      container.innerHTML = `<div class="queue-empty-state">${state.queue.length ? "No episodes match this filter." : "No dispensing episodes in queue."}</div>`;
      syncEpisodePickers();
      return;
    }
    container.innerHTML = rows.map((episode) => {
      const selected = episode.id === state.selectedId ? " selected" : "";
      const tone = statusTone(episode.status);
      return `
        <article class="queue-card${selected}" data-episode-id="${episode.id}" onclick="selectEpisode('${episode.id}')">
          <div class="q-header">
            <span class="q-disp-no">${escapeHtml(episode.dispensing_number || "—")}</span>
            <span class="q-status-badge" style="background:${tone}22;color:${tone};border:1px solid ${tone}55;">${escapeHtml(episode.status || "")}</span>
          </div>
          <div class="q-patient">${escapeHtml(episode.patient_name || "Unknown patient")}</div>
          <div class="q-meta">
            <span>${escapeHtml(episode.prescription_number || "No Rx")}</span>
            <span>${escapeHtml(episode.payment_state || "")}</span>
          </div>
        </article>`;
    }).join("");
    syncEpisodePickers();
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderEpisode(episode) {
    state.episode = episode;
    const empty = document.getElementById("empty-workspace-view");
    const active = document.getElementById("active-episode-view");
    if (!episode) {
      if (empty) empty.style.display = "";
      if (active) active.style.display = "none";
      setText("dispensing-no-display", "Select a Dispensing Episode");
      setText("episode-status-badge", "NO SELECTION");
      resetCdsBanner();
      return;
    }
    if (empty) empty.style.display = "none";
    if (active) active.style.display = "";

    setText("dispensing-no-display", episode.dispensing_number);
    const badge = document.getElementById("episode-status-badge");
    if (badge) {
      badge.textContent = episode.status;
      badge.style.background = statusTone(episode.status) + "22";
      badge.style.color = statusTone(episode.status);
    }

    setText("pat-name", episode.patient_name);
    setText("pat-num", episode.patient_number);
    setText("pat-gender", episode.patient_sex);
    setText("pat-dob", episode.patient_date_of_birth);
    const allergyTag = document.getElementById("pat-allergy-tag");
    if (allergyTag) {
      const allergies = episode.allergies || [];
      if (!allergies.length) {
        allergyTag.textContent = "Allergies: none recorded";
        allergyTag.className = "allergy-tag allergy-unknown";
      } else {
        allergyTag.textContent = "Allergies: " + allergies.map((a) => a.allergen_name).join(", ");
        allergyTag.className = "allergy-tag";
      }
    }

    setText("ins-name", episode.insurer_name || "Self-pay / uninsured");
    setText("ins-scheme", episode.scheme_name || "—");
    setText("ins-member-num", episode.membership_number || "—");
    setText("rx-num", episode.prescription_number);
    setText("prac-name", episode.prescriber_name || "—");
    setText("payment-status-tag", `Payment: ${episode.payment_state || "—"}`);

    const due = episode.amount_due || episode.paid_amount || "0.00";
    const currency = episode.currency || "KES";
    setText("pay-total-amount", formatMoney(due, currency));
    setText("modal-pay-gate-status", episode.payment_state || "PENDING");

    const body = document.getElementById("dispensing-lines-body");
    if (body) {
      const lines = episode.lines || [];
      body.innerHTML = lines.length
        ? lines.map((line) => `
            <tr>
              <td><code>${escapeHtml(String(line.prescribed_sku || "").slice(0, 8))}</code></td>
              <td>
                <strong>${escapeHtml(line.dosage_label_instructions || "Medication line")}</strong>
              </td>
              <td>${escapeHtml(line.batch_number_snapshot || "—")}<br><small>${escapeHtml(line.expiry_date_snapshot || "")}</small></td>
              <td>${escapeHtml(formatDecimal(line.quantity_authorized, 2))}</td>
              <td>${escapeHtml(formatDecimal(line.quantity_prepared, 2))}</td>
              <td>${escapeHtml(formatDecimal(line.quantity_supplied, 2))}</td>
              <td><span class="status-badge">${escapeHtml(line.status)}</span></td>
              <td><button class="btn btn-secondary btn-sm" onclick="triggerBarcodeScanModal()">Verify</button></td>
            </tr>`).join("")
        : `<tr><td colspan="8" class="muted-cell">No dispensing lines on this episode.</td></tr>`;
    }

    updateActionGates();
  }

  function resetCdsBanner(message) {
    state.screening = null;
    state.selectedFindingId = null;
    const banner = document.getElementById("cds-screening-banner");
    if (banner) {
      banner.className = "cds-banner cds-warning";
      banner.classList.remove("is-busy");
    }
    setText("cds-status-title", "CDS Clinical Screening: NOT SCREENED");
    setText("cds-details-text", message || "Open details to run or review clinical safety screening for this episode.");
    setText("cds-icon", "○");
    updateActionGates();
  }

  function cdsIsSafe() {
    return Boolean(state.screening && state.screening.status === "COMPLETE" && state.screening.safe_to_proceed);
  }

  function cdsIsBlocked() {
    return Boolean(
      state.screening
      && state.screening.status === "COMPLETE"
      && !state.screening.safe_to_proceed,
    );
  }

  function updateActionGates() {
    const checkBtn = document.getElementById("btn-pharmacist-check");
    const payBtn = document.getElementById("btn-process-payment");
    const shouldBlock = Boolean(state.episode) && !cdsIsSafe();
    [checkBtn, payBtn].forEach((btn) => {
      if (!btn) return;
      btn.classList.toggle("is-cds-blocked", shouldBlock);
      btn.title = shouldBlock
        ? "Resolve clinical safety findings before continuing"
        : btn.id === "btn-pharmacist-check"
          ? "Pharmacist Check (F3)"
          : "Process Payment (F4)";
    });
  }

  function renderCdsBanner() {
    const banner = document.getElementById("cds-screening-banner");
    const screening = state.screening;
    if (!banner) return;
    banner.classList.remove("cds-pass", "cds-warning", "cds-blocked", "is-busy");
    if (state.cdsBusy) {
      banner.classList.add("cds-warning", "is-busy");
      setText("cds-status-title", "CDS Clinical Screening: EVALUATING…");
      setText("cds-details-text", "Running safety evaluation for this basket.");
      setText("cds-icon", "…");
      return;
    }
    if (!screening) {
      banner.classList.add("cds-warning");
      setText("cds-status-title", "CDS Clinical Screening: NOT SCREENED");
      setText("cds-details-text", "Open details to run clinical safety screening for this episode.");
      setText("cds-icon", "○");
      updateActionGates();
      return;
    }
    const blocking = screening.blocking_findings || screening.blocking_count || 0;
    const severity = screening.highest_severity || "NONE";
    if (screening.safe_to_proceed) {
      banner.classList.add("cds-pass");
      setText("cds-status-title", "CDS Clinical Screening: SAFE TO PROCEED");
      setText(
        "cds-details-text",
        blocking
          ? `Resolved blockers. Highest severity ${severity}. Click for audit / findings.`
          : `No blocking findings. Highest severity ${severity || "none"}.`,
      );
      setText("cds-icon", "✓");
    } else {
      banner.classList.add("cds-blocked");
      setText("cds-status-title", `CDS Clinical Screening: BLOCKED (${blocking})`);
      setText(
        "cds-details-text",
        `${blocking} open blocking finding(s). Highest severity ${severity}. Open details to acknowledge, review, or override.`,
      );
      setText("cds-icon", "!");
    }
    updateActionGates();
  }

  function buildBasketLines(episode) {
    return (episode.lines || [])
      .map((line) => {
        const sku = line.supplied_sku || line.prescribed_sku;
        if (!sku) return null;
        const qty = Math.max(1, Math.round(Number(line.quantity_authorized) || 1));
        return {
          line_id: String(line.id),
          sku_id: String(sku),
          quantity: qty,
          dose_instructions: line.dosage_label_instructions || "",
          medicine_name: line.dosage_label_instructions || "",
          batch_number: line.batch_number_snapshot || "",
        };
      })
      .filter(Boolean);
  }

  function deviceId() {
    return (state.device && (state.device.device_id || state.device.id || state.device.code))
      || "DEMO-TERM-01";
  }

  async function evaluateClinicalScreening(episode) {
    if (!episode) {
      resetCdsBanner();
      return null;
    }
    const basket = buildBasketLines(episode);
    if (!basket.length) {
      resetCdsBanner("No dispensing lines available to screen.");
      return null;
    }
    state.cdsBusy = true;
    renderCdsBanner();
    try {
      const payload = {
        transaction_id: String(episode.id),
        device_id: String(deviceId()),
        register_id: state.shift ? String(state.shift.register || state.shift.register_id || "") : "",
        patient_id: episode.patient || null,
        prescription_id: episode.prescription || null,
        dispensing_episode_id: String(episode.id),
        basket_lines: basket,
        offline_state: false,
      };
      const screening = await api(CDS_EVALUATE_URL, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.screening = screening;
      state.selectedFindingId = (screening.findings || []).find((f) => f.resolution_status === "OPEN")?.id
        || (screening.findings || [])[0]?.id
        || null;
      return screening;
    } catch (err) {
      resetCdsBanner(`Screening failed: ${err.message}`);
      throw err;
    } finally {
      state.cdsBusy = false;
      renderCdsBanner();
    }
  }

  async function refreshScreening() {
    if (!state.screening) return null;
    const id = state.screening.screening_id || state.screening.id;
    const screening = await api(CDS_SCREENING_URL(id));
    state.screening = screening;
    renderCdsBanner();
    renderCdsModal();
    return screening;
  }

  function openFindingsHtml(findings) {
    if (!findings || !findings.length) {
      return `<div class="cds-finding-card">No clinical findings for this screening.</div>`;
    }
    return findings.map((f) => {
      const selected = String(f.id) === String(state.selectedFindingId) ? " is-selected" : "";
      const blocking = f.blocking ? " is-blocking" : "";
      return `
        <article class="cds-finding-card${blocking}${selected}" data-finding-id="${escapeHtml(f.id)}" onclick="selectCdsFinding('${escapeHtml(f.id)}')">
          <strong>${escapeHtml(f.severity || "INFO")}: ${escapeHtml(f.title || f.category || "Finding")}</strong>
          <p style="margin: 6px 0 0; font-size: 13px;">${escapeHtml(f.summary || f.clinical_explanation || "")}</p>
          <div class="cds-finding-meta">
            <span>${escapeHtml(f.category || "")}</span>
            <span>Status: ${escapeHtml(f.resolution_status || "OPEN")}</span>
            <span>${f.blocking ? "Blocking" : "Advisory"}</span>
            <span>${f.override_allowed === false ? "Override prohibited" : "Override allowed"}</span>
          </div>
          ${f.recommendation ? `<p style="margin: 8px 0 0; font-size: 12px; opacity: 0.85;">Recommendation: ${escapeHtml(f.recommendation)}</p>` : ""}
        </article>`;
    }).join("");
  }

  function renderCdsModal() {
    const summary = document.getElementById("cds-modal-summary");
    const list = document.getElementById("cds-findings-list");
    const panel = document.getElementById("cds-action-panel");
    const findingSelect = document.getElementById("cds-action-finding");
    const screening = state.screening;
    if (!summary || !list) return;
    if (!screening) {
      summary.textContent = "No screening result yet. Click Re-screen to evaluate this episode.";
      list.innerHTML = "";
      if (panel) panel.style.display = "none";
      return;
    }
    const blocking = screening.blocking_findings || screening.blocking_count || 0;
    summary.textContent = [
      `Status ${screening.status}`,
      screening.safe_to_proceed ? "safe to proceed" : "not safe to proceed",
      `${blocking} blocking`,
      `severity ${screening.highest_severity || "none"}`,
      screening.requires_pharmacist ? "pharmacist required" : "pharmacist optional",
    ].join(" · ");
    list.innerHTML = openFindingsHtml(screening.findings || []);
    if (panel) panel.style.display = "";
    if (findingSelect) {
      const findings = screening.findings || [];
      findingSelect.innerHTML = findings.map((f) => {
        const sel = String(f.id) === String(state.selectedFindingId) ? " selected" : "";
        return `<option value="${escapeHtml(f.id)}"${sel}>${escapeHtml((f.severity || "") + " — " + (f.title || f.id))}</option>`;
      }).join("") || `<option value="">No findings</option>`;
      findingSelect.onchange = () => {
        state.selectedFindingId = findingSelect.value || null;
        renderCdsModal();
      };
    }
  }

  function selectedFinding() {
    const findings = (state.screening && state.screening.findings) || [];
    return findings.find((f) => String(f.id) === String(state.selectedFindingId)) || findings[0] || null;
  }

  function pendingOverrideForFinding(findingId) {
    const overrides = (state.screening && state.screening.overrides) || [];
    return overrides.find((o) =>
      String(o.finding) === String(findingId)
      && ["REQUESTED", "UNDER_REVIEW"].includes(o.status),
    ) || null;
  }

  function cdsJustification() {
    return ((document.getElementById("cds-override-reason") || {}).value || "").trim();
  }

  function cdsApproverPayload() {
    const username = ((document.getElementById("cds-approver-user") || {}).value || "").trim();
    const password = (document.getElementById("cds-approver-pass") || {}).value || "";
    if (!username && !password) return {};
    return { approver_username: username, approver_password: password };
  }

  function handleCdsGateError(err) {
    if (err && err.cdsRelated) {
      openCdsModal();
      window.alert(err.message);
      return true;
    }
    return false;
  }

  window.selectCdsFinding = function selectCdsFinding(id) {
    state.selectedFindingId = id;
    renderCdsModal();
  };

  window.openCdsModal = function openCdsModal() {
    renderCdsModal();
    openModal("modal-cds");
  };

  window.rescreenClinicalSafety = async function rescreenClinicalSafety() {
    if (!requireEpisode()) return;
    try {
      await evaluateClinicalScreening(state.episode);
      renderCdsModal();
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.acknowledgeSelectedFinding = async function acknowledgeSelectedFinding() {
    if (!state.screening) return;
    const finding = selectedFinding();
    if (!finding) {
      window.alert("Select a finding to acknowledge.");
      return;
    }
    try {
      const screening = await api(`${CDS_SCREENING_URL(state.screening.screening_id || state.screening.id)}acknowledge/`, {
        method: "POST",
        body: JSON.stringify({
          finding_id: finding.id,
          expected_context_hash: state.screening.context_hash,
        }),
      });
      state.screening = screening;
      renderCdsBanner();
      renderCdsModal();
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.requestPharmacistReview = async function requestPharmacistReview() {
    if (!state.screening) return;
    try {
      await api(`${CDS_SCREENING_URL(state.screening.screening_id || state.screening.id)}request-pharmacist/`, {
        method: "POST",
        body: JSON.stringify({
          cashier_id: String((state.user && state.user.id) || ""),
          urgency_note: "Till request for pharmacist clinical review",
          expected_context_hash: state.screening.context_hash,
        }),
      });
      window.alert("Pharmacist review requested and audited.");
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.requestClinicalOverride = async function requestClinicalOverride() {
    if (!state.screening) return;
    const finding = selectedFinding();
    if (!finding) {
      window.alert("Select a finding to override.");
      return;
    }
    if (finding.override_allowed === false) {
      window.alert("Override is prohibited for this finding.");
      return;
    }
    const reason = cdsJustification();
    if (!reason) {
      window.alert("Enter a clinical rationale before requesting an override.");
      return;
    }
    const code = ((document.getElementById("cds-override-reason-code") || {}).value || "CLINICALLY_JUSTIFIED");
    try {
      await api(CDS_OVERRIDES_URL, {
        method: "POST",
        body: JSON.stringify({
          screening_id: state.screening.screening_id || state.screening.id,
          finding_id: finding.id,
          override_reason: code,
          requested_reason: reason,
          supporting_notes: "",
          idempotency_key: `ovr-req-${finding.id}-${Date.now()}`,
          expected_context_hash: state.screening.context_hash,
        }),
      });
      await refreshScreening();
      window.alert("Override requested. A second pharmacist must approve it.");
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.submitPharmacistReviewDecision = async function submitPharmacistReviewDecision() {
    if (!state.screening) return;
    const finding = selectedFinding();
    if (!finding) {
      window.alert("Select a finding for pharmacist approval.");
      return;
    }
    const reason = cdsJustification();
    if (!reason) {
      window.alert("Enter clinical justification for the pharmacist decision.");
      return;
    }
    const approver = cdsApproverPayload();
    if (!approver.approver_username) {
      window.alert("Enter approving pharmacist credentials (must differ from the screening cashier). Demo: demo_cds_approver.");
      return;
    }
    try {
      const screening = await api(`${CDS_SCREENING_URL(state.screening.screening_id || state.screening.id)}pharmacist-review/`, {
        method: "POST",
        body: JSON.stringify(Object.assign({
          finding_id: finding.id,
          decision: "APPROVE",
          clinical_justification: reason,
          idempotency_key: `rph-dec-${finding.id}-${Date.now()}`,
          expected_context_hash: state.screening.context_hash,
        }, approver)),
      });
      state.screening = screening;
      renderCdsBanner();
      renderCdsModal();
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.approveClinicalOverride = async function approveClinicalOverride() {
    if (!state.screening) return;
    const finding = selectedFinding();
    if (!finding) {
      window.alert("Select a finding with a pending override.");
      return;
    }
    let override = pendingOverrideForFinding(finding.id);
    if (!override) {
      window.alert("Request an override for this finding first.");
      return;
    }
    const reason = cdsJustification();
    if (!reason) {
      window.alert("Enter clinical justification for override approval.");
      return;
    }
    const approver = cdsApproverPayload();
    if (!approver.approver_username) {
      window.alert("Enter approving pharmacist credentials (demo_cds_approver).");
      return;
    }
    try {
      if (override.status === "REQUESTED") {
        override = await api(`${CDS_OVERRIDE_URL(override.id)}start-review/`, { method: "POST", body: "{}" });
      }
      await api(`${CDS_OVERRIDE_URL(override.id)}approve/`, {
        method: "POST",
        body: JSON.stringify(Object.assign({
          clinical_justification: reason,
          idempotency_key: `ovr-apr-${override.id}-${Date.now()}`,
          expected_context_hash: state.screening.context_hash,
        }, approver)),
      });
      await refreshScreening();
    } catch (err) {
      window.alert(err.message);
    }
  };

  function syncEpisodePickers() {
    const rows = filteredQueue();
    const placeholder = state.search.trim()
      ? `<option value="">${rows.length} match${rows.length === 1 ? "" : "es"} — select one…</option>`
      : `<option value="">Select a dispensing episode…</option>`;
    const options = [placeholder].concat(rows.map((episode) => {
      const selected = episode.id === state.selectedId ? " selected" : "";
      const label = `${episode.dispensing_number || "—"} · ${episode.patient_name || "Patient"} · ${episode.status || ""}`;
      return `<option value="${escapeHtml(episode.id)}"${selected}>${escapeHtml(label)}</option>`;
    }));
    if (!rows.length) {
      options.splice(0, options.length, `<option value="">No episodes match “${escapeHtml(state.search.trim() || "filter")}”</option>`);
    }
    ["episode-picker", "episode-picker-empty"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = options.join("");
    });
  }

  window.onEpisodePickerChange = function onEpisodePickerChange(selectEl) {
    const id = selectEl && selectEl.value;
    if (!id) return;
    selectEpisode(id);
  };

  function preferredEpisodeId() {
    const rows = filteredQueue();
    if (!rows.length) return null;
    const preferred = rows.find((e) => e.status === "READY_FOR_PAYMENT")
      || rows.find((e) => e.status === "CHECKING")
      || rows.find((e) => e.status === "PREPARING")
      || rows.find((e) => !["SUPPLIED", "CLOSED", "CANCELLED", "REJECTED"].includes(e.status))
      || rows[0];
    return preferred ? preferred.id : null;
  }

  window.fetchQueue = async function fetchQueue() {
    const container = document.getElementById("queue-list-container");
    if (container && !state.queue.length) {
      container.innerHTML = `<div class="queue-empty-state">Loading dispensing queue...</div>`;
    }
    try {
      const data = await api(QUEUE_URL);
      state.queue = Array.isArray(data) ? data : (data.results || []);
      renderKpis();
      renderQueue();
      syncEpisodePickers();
      const stillSelected = state.selectedId && state.queue.some((e) => e.id === state.selectedId);
      if (stillSelected) {
        await selectEpisode(state.selectedId);
      } else {
        const nextId = preferredEpisodeId();
        if (nextId) await selectEpisode(nextId);
        else renderEpisode(null);
      }
    } catch (err) {
      if (err.status === 401 || err.status === 403) return;
      if (container) {
        container.innerHTML = `<div class="queue-empty-state">Could not load queue: ${escapeHtml(err.message)}</div>`;
      }
    }
  };

  window.selectEpisode = async function selectEpisode(id) {
    state.selectedId = id;
    state.screening = null;
    renderQueue();
    syncEpisodePickers();
    try {
      const episode = await api(EPISODE_URL(id));
      renderEpisode(episode);
      try {
        await evaluateClinicalScreening(episode);
      } catch (_) {
        /* banner already shows screening failure */
      }
    } catch (err) {
      const cached = state.queue.find((e) => e.id === id);
      if (cached) {
        renderEpisode(cached);
        try {
          await evaluateClinicalScreening(cached);
        } catch (_) { /* banner shows failure */ }
      } else window.alert(err.message);
    }
  };

  window.setFilter = function setFilter(filter, button) {
    state.filter = filter;
    document.querySelectorAll(".filter-tabs .tab-btn").forEach((btn) => btn.classList.remove("active"));
    if (button) button.classList.add("active");
    else syncFilterTabs();
    renderKpis();
    renderQueue();
    const nextId = preferredEpisodeId();
    if (nextId && nextId !== state.selectedId) {
      selectEpisode(nextId);
    } else if (!nextId) {
      state.selectedId = null;
      renderEpisode(null);
      syncEpisodePickers();
    }
  };

  window.drillKpi = function drillKpi(kpi) {
    applyQueueFilter(kpi);
  };

  window.filterQueueList = function filterQueueList() {
    const input = document.getElementById("queue-search-input");
    applySearchFilter(input ? input.value : "");
  };

  window.toggleTheme = function toggleTheme() {
    document.body.classList.toggle("dark-theme");
    document.body.classList.toggle("light-theme");
    const btn = document.getElementById("btn-theme-toggle");
    if (btn) {
      const dark = document.body.classList.contains("dark-theme");
      btn.textContent = dark ? "🌙 Dark Mode" : "☀️ Light Mode";
    }
  };

  window.closeModal = function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.remove("open");
  };

  function openModal(id) {
    const el = document.getElementById(id);
    if (el) el.classList.add("open");
  }

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      document.querySelectorAll(".modal-overlay.open").forEach(function (modal) {
        modal.classList.remove("open");
      });
    }
  });

  document.addEventListener("click", function (event) {
    if (event.target && event.target.classList && event.target.classList.contains("modal-overlay")) {
      event.target.classList.remove("open");
    }
  });

  window.openShiftModal = function openShiftModal() {
    if (state.shift) {
      setText("modal-shift-num", state.shift.shift_number || "—");
    }
    openModal("modal-shift");
  };

  window.openPartialModal = () => {
    if (!requireEpisode()) return;
    const line = (state.episode.lines || [])[0];
    const auth = document.getElementById("partial-auth-qty");
    if (auth && line) auth.value = line.quantity_authorized || 0;
    openModal("modal-partial");
  };

  window.toggleHoldEpisode = async function toggleHoldEpisode() {
    if (!requireEpisode()) return;
    const next = state.episode.status === "ON_HOLD" ? "PREPARING" : "ON_HOLD";
    try {
      await api(`${EPISODE_URL(state.episode.id)}transition-state/`, {
        method: "POST",
        body: JSON.stringify({ new_status: next, notes: "POS hold/resume" }),
      });
      await fetchQueue();
      await selectEpisode(state.episode.id);
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.triggerBarcodeScanModal = () => { if (requireEpisode()) openModal("modal-barcode"); };
  window.openPharmacistCheckModal = () => {
    if (!requireEpisode()) return;
    if (!cdsIsSafe()) {
      openCdsModal();
      window.alert(
        cdsIsBlocked()
          ? "Resolve blocking clinical findings before pharmacist check / ready-for-payment."
          : "Complete clinical screening before advancing to payment.",
      );
      return;
    }
    openModal("modal-check");
  };
  window.openPaymentModal = () => {
    if (!requireEpisode()) return;
    if (!cdsIsSafe()) {
      openCdsModal();
      window.alert(
        cdsIsBlocked()
          ? "Payment is blocked until clinical findings are cleared or overridden."
          : "Run clinical screening and ensure the episode is safe to proceed before payment.",
      );
      return;
    }
    const due = state.episode.amount_due || state.episode.paid_amount || "150.00";
    setText("pay-total-amount", formatMoney(due, state.episode.currency || "KES"));
    const paid = document.getElementById("paid-amount-input");
    if (paid && !paid.value) paid.value = formatDecimal(Number(due) + 50, 2);
    calculateChange();
    openModal("modal-payment");
  };
  window.openLabelModal = () => { if (requireEpisode()) { renderLabelPreview(); openModal("modal-label"); } };
  window.openCounsellingModal = () => { if (requireEpisode()) openModal("modal-counselling"); };
  window.openCollectionModal = () => {
    if (!requireEpisode()) return;
    const name = document.getElementById("collector-name-input");
    if (name && state.episode.patient_name) name.value = state.episode.patient_name;
    openModal("modal-collection");
  };
  function requireEpisode() {
    if (!state.episode) {
      window.alert("Select a dispensing episode from the queue first.");
      return false;
    }
    return true;
  }

  window.verifyScannedBarcode = function verifyScannedBarcode() {
    const input = document.getElementById("barcode-input");
    const box = document.getElementById("scan-result-box");
    const value = (input && input.value || "").trim();
    if (!box) return;
    if (!value) {
      box.style.display = "block";
      box.textContent = "Scan or enter a batch code first.";
      return;
    }
    const [batch, expiry] = value.split("|");
    state.verifiedBatch = { batch_number: batch, expiry_date: expiry || null, raw: value };
    box.style.display = "block";
    box.innerHTML = `<strong>Verified candidate</strong><br>Batch: ${escapeHtml(batch)}<br>Expiry: ${escapeHtml(expiry || "not provided")}`;
  };

  window.applyVerifiedBatchToLine = async function applyVerifiedBatchToLine() {
    if (!requireEpisode() || !state.verifiedBatch) {
      window.alert("Verify a batch before applying it.");
      return;
    }
    try {
      await api(`${EPISODE_URL(state.episode.id)}verify-batch/`, {
        method: "POST",
        body: JSON.stringify({
          batch_number: state.verifiedBatch.batch_number,
          expiry_date: state.verifiedBatch.expiry_date,
          raw_barcode: state.verifiedBatch.raw,
        }),
      });
      closeModal("modal-barcode");
      await selectEpisode(state.episode.id);
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.submitPharmacistCheck = async function submitPharmacistCheck() {
    if (!requireEpisode()) return;
    if (!cdsIsSafe()) {
      closeModal("modal-check");
      openCdsModal();
      window.alert("Clinical screening must be safe to proceed before ready-for-payment.");
      return;
    }
    try {
      await api(`${EPISODE_URL(state.episode.id)}transition-state/`, {
        method: "POST",
        body: JSON.stringify({ new_status: "READY_FOR_PAYMENT", notes: "Pharmacist check approved at till" }),
      });
      closeModal("modal-check");
      await fetchQueue();
      await selectEpisode(state.episode.id);
    } catch (err) {
      if (!handleCdsGateError(err)) window.alert(err.message);
    }
  };

  window.toggleTenderFields = function toggleTenderFields() {
    const tender = document.getElementById("tender-type-select");
    const cash = document.getElementById("cash-fields");
    const mpesa = document.getElementById("mpesa-fields");
    if (!tender) return;
    if (cash) cash.style.display = tender.value === "CASH" ? "" : "none";
    if (mpesa) mpesa.style.display = tender.value === "MPESA" ? "" : "none";
  };

  window.calculateChange = function calculateChange() {
    const dueText = (document.getElementById("pay-total-amount") || {}).textContent || "0";
    const due = Number(String(dueText).replace(/[^\d.-]/g, "")) || 0;
    const paid = Number((document.getElementById("paid-amount-input") || {}).value || 0);
    setText("change-due-display", formatMoney(Math.max(paid - due, 0), (state.episode && state.episode.currency) || "KES"));
  };

  window.simulateMpesaPush = function simulateMpesaPush() {
    const el = document.getElementById("mpesa-push-status");
    if (el) {
      el.style.display = "block";
      el.textContent = "STK push simulated — waiting for customer confirmation…";
    }
  };

  window.submitPayment = async function submitPayment() {
    if (!requireEpisode()) return;
    if (!cdsIsSafe()) {
      closeModal("modal-payment");
      openCdsModal();
      window.alert("Payment requires a current clinical screening that is safe to proceed.");
      return;
    }
    const tender = (document.getElementById("tender-type-select") || {}).value || "CASH";
    const reference = (document.getElementById("pay-ref-input") || {}).value || `POS-${Date.now()}`;
    const amount = Number((document.getElementById("paid-amount-input") || {}).value || 0);
    try {
      await api(`${EPISODE_URL(state.episode.id)}process-payment/`, {
        method: "POST",
        body: JSON.stringify({
          tender_type: tender === "CREDIT_ACCOUNT" ? "CASH" : tender,
          amount_tendered: String(amount || state.episode.amount_due || "0"),
          payment_reference: reference,
        }),
      });
      closeModal("modal-payment");
      await fetchQueue();
      await selectEpisode(state.episode.id);
    } catch (err) {
      if (!handleCdsGateError(err)) window.alert(err.message);
    }
  };

  window.renderLabelPreview = function renderLabelPreview() {
    const wrap = document.getElementById("label-preview-wrapper");
    if (!wrap || !state.episode) return;
    const line = (state.episode.lines || [])[0] || {};
    wrap.innerHTML = `
      <div style="background:#fff;color:#0f172a;padding:16px;border-radius:8px;font-family:monospace;">
        <strong>${escapeHtml(state.episode.patient_name || "Patient")}</strong><br>
        ${escapeHtml(line.dosage_label_instructions || "Take as directed")}<br>
        Batch ${escapeHtml(line.batch_number_snapshot || "—")} · Exp ${escapeHtml(line.expiry_date_snapshot || "—")}<br>
        Rx ${escapeHtml(state.episode.prescription_number || "—")} · ${escapeHtml(state.episode.dispensing_number || "")}
      </div>`;
  };

  window.printCurrentLabel = function printCurrentLabel() {
    window.alert("Label print job queued for the till printer.");
    closeModal("modal-label");
  };

  window.submitCounselling = async function submitCounselling() {
    if (!requireEpisode()) return;
    const notes = (document.getElementById("counselling-notes") || {}).value || "Counselling completed at till.";
    try {
      await api(`${EPISODE_URL(state.episode.id)}record-counselling/`, {
        method: "POST",
        body: JSON.stringify({ notes, counselling_completed: true }),
      });
      closeModal("modal-counselling");
      await selectEpisode(state.episode.id);
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.submitCollection = async function submitCollection() {
    if (!requireEpisode()) return;
    try {
      await api(`${EPISODE_URL(state.episode.id)}confirm-collection/`, {
        method: "POST",
        body: JSON.stringify({
          collector_name: (document.getElementById("collector-name-input") || {}).value || "",
          collector_id_number: (document.getElementById("collector-id-input") || {}).value || "",
          collector_relationship: (document.getElementById("collector-rel-select") || {}).value || "SELF",
        }),
      });
      closeModal("modal-collection");
      await fetchQueue();
      await selectEpisode(state.episode.id);
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.submitPartialDispensing = async function submitPartialDispensing() {
    if (!requireEpisode()) return;
    try {
      await api(`${EPISODE_URL(state.episode.id)}dispense-partial/`, {
        method: "POST",
        body: JSON.stringify({
          quantity: Number((document.getElementById("partial-stage-qty") || {}).value || 0),
          reason: (document.getElementById("partial-reason-select") || {}).value || "STOCK_SHORTAGE",
        }),
      });
      closeModal("modal-partial");
      await fetchQueue();
      await selectEpisode(state.episode.id);
    } catch (err) {
      window.alert(err.message);
    }
  };

  window.endShift = async function endShift() {
    if (!state.shift) {
      window.alert("No open POS shift found.");
      return;
    }
    try {
      await api(`${SHIFT_URL}${state.shift.id}/end/`, {
        method: "POST",
        body: JSON.stringify({
          controlled_stock_end_count: Number((document.getElementById("shift-end-count") || {}).value || 0),
          notes: (document.getElementById("shift-notes") || {}).value || "",
        }),
      });
      closeModal("modal-shift");
      await loadShiftAndDevice();
    } catch (err) {
      window.alert(err.message);
    }
  };


  async function loadShiftAndDevice() {
    try {
      const shifts = await api(SHIFT_URL);
      const rows = Array.isArray(shifts) ? shifts : (shifts.results || []);
      state.shift = rows.find((s) => s.status === "OPEN") || rows[0] || null;
      if (state.shift) {
        setText("shift-info", "Shift #" + state.shift.shift_number + " · " + state.shift.status);
      }
    } catch (_) { /* optional */ }

    try {
      const devices = await api(DEVICE_URL);
      const rows = Array.isArray(devices) ? devices : (devices.results || []);
      const device = rows[0];
      if (device) {
        state.device = device;
        setText("tel-printer", device.printer_paper_level || device.status || "OK");
        setText("tel-scanner", device.scanner_connected ? "CONNECTED" : "OFFLINE");
      }
    } catch (_) { /* optional */ }

    try {
      const registers = await api(REGISTER_URL);
      const rows = Array.isArray(registers) ? registers : (registers.results || []);
      const till = rows[0];
      if (till) {
        setText("terminal-branch", (till.name || till.code) + " · " + (till.state || "READY"));
      }
    } catch (_) { /* optional */ }
  }

  async function bootstrap() {
    await loadShiftAndDevice();
    await fetchQueue();
    if (!state.queue.length) {
      const container = document.getElementById("queue-list-container");
      if (container) {
        container.innerHTML = "<div class=\"queue-empty-state\">No dispensing episodes in queue for this workspace.</div>";
      }
    }
  }

  async function ensureSession() {
    try {
      const session = await api(SESSION_URL);
      if (session && session.authenticated && session.user) {
        updateSessionUi(session.user);
        if (!session.user.tenant_id && session.user.is_platform_admin) {
          showLogin("Platform admin sessions have no till workspace. Sign in as demo_dispensing_rph to see seeded episodes.");
          return false;
        }
        return true;
      }
    } catch (_) { /* treat as signed out */ }
    updateSessionUi(null);
    showLogin("Sign in as demo_dispensing_rph to load the seeded dispensing queue.");
    return false;
  }

  window.toggleQueuePanel = function toggleQueuePanel(force) {
    const collapsed = typeof force === "boolean"
      ? force
      : !document.getElementById("workstation-container")?.classList.contains("queue-collapsed");
    setQueuePanelCollapsed(collapsed);
  };

  function setQueuePanelCollapsed(collapsed) {
    const workstation = document.getElementById("workstation-container");
    const panel = document.getElementById("queue-panel");
    const toggle = document.getElementById("btn-queue-toggle");
    const reveal = document.getElementById("btn-queue-reveal");
    if (!workstation || !panel) return;

    workstation.classList.toggle("queue-collapsed", collapsed);
    panel.classList.toggle("is-collapsed", collapsed);

    if (toggle) {
      toggle.textContent = collapsed ? "▶" : "◀";
      toggle.title = collapsed ? "Show queue (F9)" : "Hide queue (F9)";
      toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
      toggle.setAttribute("aria-label", collapsed ? "Show dispensing queue" : "Hide dispensing queue");
    }
    if (reveal) {
      if (collapsed) reveal.removeAttribute("hidden");
      else reveal.setAttribute("hidden", "");
    }

    try {
      localStorage.setItem("pos.queueCollapsed", collapsed ? "1" : "0");
    } catch (_) { /* ignore */ }
  }

  function restoreQueuePanelPreference() {
    try {
      if (localStorage.getItem("pos.queueCollapsed") === "1") {
        setQueuePanelCollapsed(true);
      }
    } catch (_) { /* ignore */ }
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "F2") { event.preventDefault(); triggerBarcodeScanModal(); }
    if (event.key === "F3") { event.preventDefault(); openPharmacistCheckModal(); }
    if (event.key === "F4") { event.preventDefault(); openPaymentModal(); }
    if (event.key === "F5") { event.preventDefault(); openLabelModal(); }
    if (event.key === "F6") { event.preventDefault(); openCounsellingModal(); }
    if (event.key === "F7") { event.preventDefault(); openCollectionModal(); }
    if (event.key === "F8") { event.preventDefault(); openShiftModal(); }
    if (event.key === "F9") { event.preventDefault(); toggleQueuePanel(); }
  });

  document.addEventListener("DOMContentLoaded", async () => {
    restoreQueuePanelPreference();
    const signedIn = await ensureSession();
    if (signedIn) {
      try {
        await bootstrap();
      } catch (_) { /* login overlay already shown when auth fails */ }
    }
  });
})();
