import { api } from "./api.js";

const root = document.querySelector("#app");
const modal = document.querySelector("#modal");
const toastElement = document.querySelector("#toast");

const emptyFilters = () => ({ doctor: "", date: "", status: "", stage: "", patient: "" });

const state = {
  user: null, page: "overview",
  patients: [], doctors: [], follows: [], requests: [], messages: [],
  events: [], activity: [], dashboard: null,
  filters: emptyFilters(), month: "", activityFilter: "",
  detail: null, loading: false, again: false,
  selectedFollowUps: new Set(),
};

const homes = {
  doctor: "#/doctor/dashboard",
  receptionist: "#/receptionist/dashboard",
  admin: "#/admin/dashboard",
};

const statusNames = ["UPCOMING", "DUE_TODAY", "OVERDUE", "CONFIRMED",
  "RESCHEDULE_REQUESTED", "RESCHEDULED", "COMPLETED"];

const treatmentStages = ["Initial consultation", "Diagnostic assessment",
  "Ovulation induction", "IUI", "IVF preparation", "Stimulation",
  "Embryo transfer", "Post-treatment review", "Other"];

const languages = { English: "English", Tamil: "Tamil", Telugu: "Telugu", en_US: "English", ta: "Tamil", te: "Telugu", hi: "Hindi", es: "Spanish", ar: "Arabic" };

const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const label = value => String(value ?? "").replaceAll("_", " ");
const dateLabel = value => value
  ? new Date(`${value}T12:00:00`).toLocaleDateString(undefined,
      { day: "numeric", month: "short", year: "numeric" })
  : "—";
const timeLabel = value => value ? new Date(value).toLocaleString() : "—";
const patientId = id => (typeof id === "string" && id.includes("-"))
  ? (id.startsWith("DEMO-") ? id : `P-${id.slice(0, 8).toUpperCase()}`)
  : `P-${String(id).padStart(4, "0")}`;
const badge = value =>
  `<span class="badge ${escape(value)}">${escape(label(value || "NOT_SENT"))}</span>`;
const canManage = () => ["receptionist", "admin"].includes(state.user?.role);
const option = (value, text, selected) =>
  `<option value="${escape(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escape(text)}</option>`;

const serverFilters = () => ({
  doctor_id: state.filters.doctor, date: state.filters.date,
  status: state.filters.status, stage: state.filters.stage,
  patient_id: state.filters.patient,
});

function notify(message) {
  toastElement.textContent = message;
  toastElement.classList.add("visible");
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => toastElement.classList.remove("visible"), 4000);
}

function empty(title, description) {
  return `<div class="empty"><strong>${escape(title)}</strong>${escape(description)}</div>`;
}

function renderLogin() {
  state.user = null;
  state.detail = null;
  if (modal.open) modal.close();
  history.replaceState(null, "", "#/login");

  root.innerHTML = `
    <main class="login">
      <section class="login-story">
        <div class="logo"><span class="logo-mark">✦</span> bloom clinic</div>
        <div>
          <div class="eyebrow">Continuity of care</div>
          <h1>Every follow-up.<br>Thoughtfully managed.</h1>
          <p>A private workspace for your clinic’s patient care, appointments, and follow-up coordination.</p>
        </div>
        <small>Internal clinical operations · Authorized staff only</small>
      </section>
      <section class="login-form-side">
        <div class="login-card">
          <div class="eyebrow">Staff workspace</div>
          <h2>Welcome back</h2>
          <p class="muted">Sign in to access your clinic dashboard.</p>
          <form id="login-form">
            <div class="field">
              <label for="email">Email / Username</label>
              <input id="email" name="email" type="email" autocomplete="username" placeholder="you@clinic.demo" required>
            </div>
            <div class="field">
              <label for="password">Password</label>
              <input id="password" name="password" type="password" autocomplete="current-password" required>
            </div>
            <div class="error" id="login-error" role="alert"></div>
            <button class="btn primary" type="submit">Sign in securely →</button>
          </form>
          <div class="login-demo">
            <strong>Authorized demo accounts</strong>
            <div>Doctor 1 · doctor1@clinic.demo</div>
            <div>Doctor 2 · doctor2@clinic.demo</div>
            <div>Receptionist · reception@clinic.demo</div>
            <div>Admin · admin@clinic.demo</div>
            <p>Use the password configured on the server. Your role is determined by the backend after sign-in.</p>
          </div>
        </div>
      </section>
    </main>`;

  document.querySelector("#login-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = form.querySelector("button");
    button.disabled = true;
    document.querySelector("#login-error").textContent = "";
    try {
      state.user = await api.login(Object.fromEntries(new FormData(form)));
      state.page = "overview";
      state.filters = emptyFilters();
      state.month = "";
      await reload();
    } catch (error) {
      const target = document.querySelector("#login-error");
      if (target) target.textContent = error.message;
      else notify(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

function renderShell() {
  const user = state.user;
  const navigation = [
    ["overview", "◫", "Overview"],
    ["patients", "♧", "Patients"],
    ...(canManage() ? [["doctors", "✚", "Doctors"]] : []),
    ["calendar", "▦", "Calendar"],
    ["requests", "↻", "Reschedule requests"],
    ["messages", "◌", "WhatsApp activity"],
    ...(user.role === "admin" ? [["activity", "≋", "Clinic activity"]] : []),
  ];

  history.replaceState(null, "", state.page === "overview" ? homes[user.role] : `#/${state.page}`);

  root.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="logo"><span class="logo-mark">✦</span> bloom</div>
        <div class="eyebrow">Clinic workspace</div>
        <nav class="nav" aria-label="Main navigation">
          ${navigation.map(([page, symbol, text]) => `
            <button data-nav="${page}" class="${state.page === page ? "active" : ""}">
              <span class="nav-symbol">${symbol}</span>${text}
            </button>`).join("")}
        </nav>
        <div class="sidebar-footer">
          <div class="user-box">
            <div class="avatar">${escape(user.name.split(" ").map(v => v[0]).join(""))}</div>
            <div><strong>${escape(user.name)}</strong><small>${escape(user.role)}</small></div>
          </div>
          <button class="btn small" data-action="logout">Sign out</button>
        </div>
      </aside>
      <main class="main">
        <div class="topline">
          <span>Bloom Fertility Clinic / <strong>${escape(label(state.page))}</strong></span>
          <span><span class="live-dot"></span>Synced ${escape(timeLabel(state.dashboard.generated_at))}</span>
        </div>
        <div id="content"></div>
      </main>
    </div>`;
  renderContent();
}

function pageHeading(title, description, buttons = "") {
  return `<header class="page-heading">
    <div><h1>${escape(title)}</h1><p>${escape(description)}</p></div>
    <div class="actions">${buttons}</div></header>`;
}

function createButtons() {
  if (!canManage()) return "";
  return `<button class="btn" data-action="new-follow">＋ Create follow-up</button>
    <button class="btn primary" data-action="new-patient">＋ Add patient</button>`;
}

function dashboardCards() {
  const c = state.dashboard.counts;
  const role = state.user.role;
  const cards = [
    ["total_patients", role === "doctor" ? "My Patients" : "Total Patients"],
    ...(role === "admin"
      ? [["doctor1_patients", "Doctor 1 Patients"], ["doctor2_patients", "Doctor 2 Patients"]] : []),
    ["today", "Today’s Follow-ups"],
    ["upcoming", role === "receptionist" ? "Upcoming Follow-ups" : "Upcoming"],
    ["overdue", "Overdue"],
    ["confirmed", "Confirmed"],
    ["rescheduled", "Rescheduled"],
    ...(role === "receptionist" ? [["pending_requests", "Pending Reschedule Requests"]] : []),
    ...(role === "admin" ? [["pending_requests", "Pending Requests"]] : []),
  ];
  return `<section class="metrics" aria-label="Dashboard statistics">
    ${cards.map(([key, title]) => `
      <article class="metric ${key === "overdue" ? "alert" : ""}">
        <div class="metric-name">${escape(title)}</div>
        <div class="metric-value">${c[key]}</div>
        <div class="metric-foot">From clinic records</div>
      </article>`).join("")}</section>`;
}

function renderFilters() {
  const f = state.filters;
  const stages = [...new Set(state.patients.map(p => p.treatment_stage))].sort();
  return `<div class="filters">
    <div><label for="filter-doctor">Doctor</label>
      <select id="filter-doctor" data-filter="doctor">
        ${option("", "All accessible doctors", f.doctor)}
        ${state.doctors.map(d => option(d.id, d.name, f.doctor)).join("")}
      </select></div>
    <div><label for="filter-date">Follow-up date</label>
      <input id="filter-date" type="date" data-filter="date" value="${escape(f.date)}"></div>
    <div><label for="filter-status">Status</label>
      <select id="filter-status" data-filter="status">
        ${option("", "All statuses", f.status)}
        ${statusNames.map(s => option(s, label(s), f.status)).join("")}
      </select></div>
    <div><label for="filter-stage">Treatment stage</label>
      <select id="filter-stage" data-filter="stage">
        ${option("", "All treatment stages", f.stage)}
        ${stages.map(s => option(s, s, f.stage)).join("")}
      </select></div>
    <div><label for="filter-patient">Patient</label>
      <select id="filter-patient" data-filter="patient">
        ${option("", "All patients", f.patient)}
        ${state.patients.map(p => option(p.id, p.name, f.patient)).join("")}
      </select></div>
  </div>`;
}

function followTable(items, compact = false) {
  if (!items.length) {
    return empty("No follow-ups to display",
      "Create a follow-up or adjust the filters to see clinic records.");
  }
  const showCheckbox = canManage() && !compact;
  const allSelected = showCheckbox && items.length > 0 && items.every(i => state.selectedFollowUps.has(String(i.id)));
  return `<div class="table-wrap"><table>
    <thead><tr>
      ${showCheckbox ? `<th><input type="checkbox" id="select-all-visible" ${allSelected ? "checked" : ""} title="Select all visible"></th>` : ""}
      <th>Patient ID</th><th>Patient name</th><th>Follow-up date</th>
      <th>Follow-up type</th><th>Status</th><th>WhatsApp status</th><th>Action</th>
    </tr></thead>
    <tbody>${items.map(item => `
      <tr>
        ${showCheckbox ? `<td><input type="checkbox" class="follow-checkbox" data-id="${item.id}" ${state.selectedFollowUps.has(String(item.id)) ? "checked" : ""}></td>` : ""}
        <td class="muted">${patientId(item.patient_id)}</td>
        <td><strong>${escape(item.patient_name)}</strong><small>${escape(item.doctor_name)}</small></td>
        <td>${dateLabel(item.follow_up_date)}</td>
        <td>${escape(item.follow_up_type)}</td>
        <td>${badge(item.status)}</td>
        <td>${badge(item.whatsapp_status)}</td>
        <td><div class="actions">
          <button class="btn link small" data-action="patient" data-id="${item.patient_id}">View Patient</button>
          <button class="btn link small" data-action="follow" data-id="${item.id}">View Follow-up</button>
          ${!compact ? `<button class="btn link small" data-action="history" data-id="${item.patient_id}">View History</button>` : ""}
        </div></td>
      </tr>`).join("")}</tbody></table></div>`;
}

function renderReminderBar() {
  if (!canManage()) return "";
  const eligibleCount = state.follows.filter(f => f.whatsapp_opt_in && f.status !== "COMPLETED").length;
  const selectedCount = state.selectedFollowUps.size;
  return `
    <div class="reminder-bar">
      <div class="reminder-bar-info">
        <span class="badge ${eligibleCount > 0 ? "DUE_TODAY" : "muted"}">✦ ${eligibleCount} Patients Eligible for Reminders</span>
        <span class="muted">${selectedCount > 0 ? `${selectedCount} selected` : "No individual selection (will target eligible)"}</span>
      </div>
      <div class="reminder-bar-actions">
        <button class="btn small" data-action="select-all-eligible">Select All Eligible (${eligibleCount})</button>
        ${selectedCount > 0 ? `<button class="btn small" data-action="clear-selection">Clear Selection</button>` : ""}
        <button class="btn primary small" data-action="open-reminders">Send Follow-up Reminders ${selectedCount > 0 ? `(${selectedCount})` : ""}</button>
      </div>
    </div>`;
}

function renderOverview() {
  const title = { doctor: "Doctor Dashboard", receptionist: "Receptionist Dashboard",
    admin: "Admin Dashboard" }[state.user.role];
  return `
    ${pageHeading(title,
      `${dateLabel(state.dashboard.today)} · Patient care and follow-up coordination`,
      createButtons())}
    ${dashboardCards()}
    ${renderReminderBar()}
    <section class="panel">
      <div class="panel-head">
        <div><h2>Follow-up worklist</h2>
          <p>${state.user.role === "doctor"
            ? "Only patients assigned to you are returned by the backend."
            : "Coordinate follow-ups across both doctors. Filters are applied by the backend."}</p></div>
        <button class="btn small" data-action="reset-filters">Clear filters</button>
      </div>
      ${renderFilters()}
      ${followTable(state.follows)}
    </section>
    ${state.user.role === "admin" ? renderActivityPanel(12) : ""}`;
}

function renderPatients() {
  const f = state.filters;
  const followFilter = f.date || f.status;
  const items = state.patients.filter(p =>
    (!f.doctor || String(p.doctor_id) === f.doctor) &&
    (!f.stage || p.treatment_stage === f.stage) &&
    (!f.patient || String(p.id) === f.patient) &&
    (!followFilter || state.follows.some(item => item.patient_id === p.id)));

  return `
    ${pageHeading("Patient directory", "Patient records and assigned care teams.", createButtons())}
    <section class="panel">
      <div class="panel-head">
        <div><h2>${items.length} accessible patients</h2>
          <p>Clinical information is restricted by your account role.</p></div>
        <button class="btn small" data-action="reset-filters">Clear filters</button>
      </div>
      ${renderFilters()}
      ${!items.length ? empty("No patients to display",
        "The receptionist or admin can add a patient and assign a doctor.") : `
      <div class="table-wrap"><table>
        <thead><tr><th>Patient ID</th><th>Patient</th><th>Phone</th><th>Doctor</th>
          <th>Treatment stage</th><th>Action</th></tr></thead>
        <tbody>${items.map(p => `
          <tr>
            <td>${patientId(p.id)}</td>
            <td><strong>${escape(p.name)}</strong>
              <small>${escape(languages[p.preferred_language] || p.preferred_language)}</small></td>
            <td>${escape(p.phone)}</td><td>${escape(p.doctor_name)}</td>
            <td>${escape(p.treatment_stage)}</td>
            <td class="actions">
              <button class="btn small" data-action="patient" data-id="${p.id}">View record</button>
              ${canManage() ? `
                <button class="btn small" data-action="edit-patient" data-id="${p.id}">Edit</button>
                <button class="btn small" data-action="new-follow" data-id="${p.id}">Follow-up</button>` : ""}
            </td>
          </tr>`).join("")}</tbody></table></div>`}
    </section>`;
}

function renderDoctors() {
  return `
    ${pageHeading("Doctors", "Clinic physicians and their assigned caseloads.")}
    <section class="panel">
      <div class="table-wrap"><table>
        <thead><tr><th>Doctor</th><th>Assigned patients</th><th>Action</th></tr></thead>
        <tbody>${state.doctors.map(d => `
          <tr><td><strong>${escape(d.name)}</strong></td>
          <td>${d.patient_count}</td>
          <td><button class="btn small" data-action="doctor-patients" data-id="${d.id}">View patients</button></td></tr>
        `).join("")}</tbody></table></div>
    </section>`;
}

function requestsTable(items, actions = true) {
  if (!items.length) {
    return empty("No reschedule requests",
      "Patient requests appear here after a verified WhatsApp response.");
  }
  return `<div class="table-wrap"><table>
    <thead><tr><th>Patient</th><th>Doctor</th><th>Original date</th><th>Requested date</th>
      <th>Request date</th><th>Status</th>${actions ? "<th>Action</th>" : ""}</tr></thead>
    <tbody>${items.map(r => `
      <tr>
        <td>${escape(r.patient_name)}</td><td>${escape(r.doctor_name)}</td>
        <td>${dateLabel(r.original_date)}</td><td>${dateLabel(r.requested_date)}</td>
        <td>${escape(timeLabel(r.request_date))}</td><td>${badge(r.status)}</td>
        ${actions ? `<td><div class="actions">
          ${r.status === "PENDING" ? `
            <button class="btn primary small" data-action="approve" data-id="${r.id}">Approve</button>
            <button class="btn danger small" data-action="reject" data-id="${r.id}">Reject</button>` : "—"}
        </div></td>` : ""}
      </tr>`).join("")}</tbody></table></div>`;
}

function renderRequests() {
  return `
    ${pageHeading("Reschedule requests",
      "Review patient-requested dates without losing the original appointment history.")}
    <div class="notice">Approval moves the follow-up to the requested date and marks it RESCHEDULED.
      Rejection leaves the original date unchanged. Both decisions are kept in the history.</div>
    <section class="panel">
      <div class="panel-head"><div><h2>Patient requests</h2>
        <p>Pending requests and previous decisions.</p></div></div>
      ${requestsTable(state.requests)}
    </section>`;
}

function shiftMonth(offset) {
  const [year, month] = state.month.split("-").map(Number);
  const shifted = new Date(year, month - 1 + offset, 1);
  state.month = `${shifted.getFullYear()}-${String(shifted.getMonth() + 1).padStart(2, "0")}`;
  renderContent();
}

function renderCalendar() {
  const [year, month] = state.month.split("-").map(Number);
  const first = new Date(year, month - 1, 1);
  const start = new Date(year, month - 1, 1 - first.getDay());
  const title = first.toLocaleDateString(undefined, { month: "long", year: "numeric" });

  const cells = Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    const iso = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, "0")}-${String(day.getDate()).padStart(2, "0")}`;
    const dayEvents = state.events.filter(e => e.follow_up_date === iso);
    return `<div class="calendar-day ${day.getMonth() !== month - 1 ? "off" : ""} ${iso === state.dashboard.today ? "today" : ""}">
      <div class="day-number">${day.getDate()}</div>
      ${dayEvents.map(e => `
        <button class="calendar-event badge ${escape(e.status)}" data-action="follow" data-id="${e.id}"
          title="${escape(`${e.patient_name} · ${e.doctor_name} · ${label(e.status)}`)}">
          <span>${escape(e.patient_name)}</span><span>${escape(label(e.status))}</span>
        </button>`).join("")}
    </div>`;
  }).join("");

  return `
    ${pageHeading("Follow-up calendar", `Clinic timezone: ${state.dashboard.timezone}`, createButtons())}
    <section class="panel">
      <div class="panel-head">
        <div><h2>${escape(title)}</h2><p>Click a follow-up to open its details.</p></div>
        <div class="calendar-toolbar">
          <button class="btn small" data-action="previous-month" aria-label="Previous month">←</button>
          <button class="btn small" data-action="calendar-today">Today</button>
          <button class="btn small" data-action="next-month" aria-label="Next month">→</button>
        </div>
      </div>
      ${renderFilters()}
      <div class="calendar-grid">
        ${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => `<div class="calendar-weekday">${d}</div>`).join("")}
        ${cells}
      </div>
      <div class="legend">${statusNames.filter(s => s !== "COMPLETED").map(badge).join("")}</div>
    </section>`;
}

function renderMessages() {
  return `
    ${pageHeading("WhatsApp activity", "Provider-backed message records and delivery updates.")}
    <section class="panel">
      <div class="panel-head"><div><h2>Reminder messages</h2>
        <p>Delivered, read and failed statuses are received only from signed Meta webhooks.</p></div></div>
      ${!state.messages.length ? empty("No messages have been scheduled",
        "Configured reminders are queued when opted-in patients have due-today follow-ups.") : `
      <div class="table-wrap"><table>
        <thead><tr><th>Patient</th><th>Doctor</th><th>Follow-up</th><th>Status</th>
          <th>Created</th><th>Updated</th><th>Information</th></tr></thead>
        <tbody>${state.messages.map(m => `
          <tr><td>${escape(m.patient_name)}</td><td>${escape(m.doctor_name)}</td>
          <td>#${m.follow_up_id}</td><td>${badge(m.status)}</td>
          <td>${escape(timeLabel(m.created_at))}</td><td>${escape(timeLabel(m.updated_at))}</td>
          <td>${escape(m.error || "—")}</td></tr>`).join("")}</tbody></table></div>`}
    </section>`;
}

function selectedActivity() {
  const filter = state.activityFilter;
  if (!filter) return state.activity;
  if (["doctor", "receptionist"].includes(filter)) {
    return state.activity.filter(a => a.actor_role === filter);
  }
  return state.activity.filter(a => a.category === filter);
}

function renderActivityPanel(limit = null) {
  const items = selectedActivity().slice(0, limit || 1000);
  const groups = [
    ["", "All clinic activity"], ["doctor", "Doctor activity"],
    ["receptionist", "Receptionist activity"], ["patient", "Patient activity"],
    ["follow_up", "Follow-up activity"], ["whatsapp", "WhatsApp message activity"],
    ["reschedule", "Reschedule history"], ["system", "System activity"],
  ];
  return `<section class="panel">
    <div class="panel-head">
      <div><h2>Clinic activity</h2><p>Persistent audit trail of clinic operations.</p></div>
      <select id="activity-filter" aria-label="Activity category">
        ${groups.map(([v, t]) => option(v, t, state.activityFilter)).join("")}
      </select>
    </div>
    ${!items.length ? empty("No matching activity", "Recorded operations will appear here.") : `
    <div class="table-wrap"><table>
      <thead><tr><th>Time</th><th>Actor</th><th>Category</th><th>Action</th><th>Patient</th><th>Details</th></tr></thead>
      <tbody>${items.map(a => `
        <tr><td>${escape(timeLabel(a.created_at))}</td><td>${escape(a.actor_name)}</td>
        <td>${escape(label(a.category))}</td><td>${escape(label(a.action))}</td>
        <td>${escape(a.patient_name || "—")}</td>
        <td><button class="btn small" data-action="activity-detail" data-id="${a.id}">View</button></td></tr>
      `).join("")}</tbody></table></div>`}
  </section>`;
}

function renderContent() {
  const target = document.querySelector("#content");
  if (!target) return;
  const renderers = {
    overview: renderOverview, patients: renderPatients, doctors: renderDoctors,
    calendar: renderCalendar, requests: renderRequests, messages: renderMessages,
    activity: () => pageHeading("Clinic activity",
      "Doctor, receptionist, patient, messaging, and system history.") + renderActivityPanel(),
  };
  target.innerHTML = (renderers[state.page] || renderOverview)();
}

function openModal(title, content, preserveDetail = false) {
  if (!preserveDetail) state.detail = null;
  modal.innerHTML = `
    <div class="modal-head">
      <h2 id="modal-title">${escape(title)}</h2>
      <button class="btn small" data-action="close-modal" aria-label="Close dialog">✕</button>
    </div>
    <div class="modal-body">${content}</div>`;
  if (!modal.open) modal.showModal();
}

const detailField = (title, content) =>
  `<div><small>${escape(title)}</small><strong>${content}</strong></div>`;

function historyList(items) {
  if (!items.length) return empty("No history yet", "Recorded patient events will appear here.");
  return items.map(item => {
    let details = {};
    try { details = JSON.parse(item.details); } catch {}
    return `<article class="history-item">
      <strong>${escape(label(item.action))}</strong>
      <small>${escape(timeLabel(item.created_at))} · ${escape(item.actor_name)}</small>
      ${Object.keys(details).length ? `<pre>${escape(JSON.stringify(details, null, 2))}</pre>` : ""}
    </article>`;
  }).join("");
}

async function showPatient(id, historyOnly = false, polling = false) {
  const patient = await api.patient(id, polling);
  state.detail = { kind: "patient", id, historyOnly };
  const current = patient.current_follow_up;

  const content = `
    ${!historyOnly ? `
      <div class="detail-grid">
        ${detailField("Patient ID", patientId(patient.id))}
        ${detailField("Patient name", escape(patient.name))}
        ${detailField("Phone", escape(patient.phone))}
        ${detailField("Preferred language", escape(languages[patient.preferred_language] || patient.preferred_language))}
        ${detailField("Assigned doctor", escape(patient.doctor_name))}
        ${detailField("Treatment stage", escape(patient.treatment_stage))}
        ${detailField("Current follow-up", current
          ? `${dateLabel(current.follow_up_date)} · ${escape(current.follow_up_type)}` : "No active follow-up")}
        ${detailField("Follow-up status", current ? badge(current.status) : "—")}
        ${detailField("WhatsApp status", badge(current?.whatsapp_status || "NOT_SENT"))}
        ${detailField("WhatsApp consent", patient.whatsapp_opt_in ? "Opted in" : "Not opted in")}
      </div>
      ${canManage() ? `<div class="actions">
        <button class="btn" data-action="edit-patient" data-id="${id}">Edit patient</button>
        <button class="btn primary" data-action="new-follow" data-id="${id}">Create follow-up</button>
        <button class="btn" data-action="new-appointment" data-id="${id}">Record appointment</button>
      </div>` : ""}
      <h3 class="section-label">Follow-ups</h3>
      ${followTable(patient.follow_ups, true)}
      <h3 class="section-label">Appointments</h3>
      ${patient.appointments.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>Status</th><th>Note</th></tr></thead>
        <tbody>${patient.appointments.map(a => `
          <tr><td>${dateLabel(a.appointment_date)}</td><td>${escape(a.status)}</td><td>${escape(a.note || "—")}</td></tr>
        `).join("")}</tbody></table></div>` : `<p class="muted">No appointments have been recorded.</p>`}
      <h3 class="section-label">Reschedule history</h3>
      ${requestsTable(patient.reschedule_requests, false)}` : ""}
    <h3 class="section-label">Patient history</h3>
    <p class="muted">Appointments, follow-ups, confirmations, reschedule requests, changes, and completions.</p>
    ${historyList(patient.history)}`;

  const scroll = polling ? modal.scrollTop : 0;
  openModal(historyOnly ? `${patient.name} — History` : `${patient.name} — Patient record`, content, true);
  if (polling) modal.scrollTop = scroll;
}

async function showFollow(id, polling = false) {
  const item = await api.followUp(id);
  state.detail = { kind: "follow", id };
  const content = `
    <div class="detail-grid">
      ${detailField("Follow-up ID", `#${item.id}`)}
      ${detailField("Patient", escape(item.patient_name))}
      ${detailField("Patient ID", patientId(item.patient_id))}
      ${detailField("Assigned doctor", escape(item.doctor_name))}
      ${detailField("Follow-up date", dateLabel(item.follow_up_date))}
      ${detailField("Follow-up type", escape(item.follow_up_type))}
      ${detailField("Status", badge(item.status))}
      ${detailField("WhatsApp status", badge(item.whatsapp_status))}
      ${detailField("Patient response", item.patient_response ? badge(item.patient_response) : "No response recorded")}
    </div>
    <div class="actions">
      <button class="btn" data-action="patient" data-id="${item.patient_id}">View patient</button>
      ${canManage() && item.status !== "COMPLETED" ? `
        <button class="btn" data-action="edit-follow" data-id="${item.id}">Edit follow-up</button>
        <button class="btn primary" data-action="complete-follow" data-id="${item.id}">Mark completed</button>` : ""}
    </div>
    <h3 class="section-label">Follow-up history</h3>
    ${historyList(item.history)}`;
  const scroll = polling ? modal.scrollTop : 0;
  openModal(`Follow-up #${item.id}`, content, true);
  if (polling) modal.scrollTop = scroll;
}

const inputField = (name, title, value = "", type = "text", extra = "") => `
  <div class="field"><label for="form-${name}">${escape(title)}</label>
  <input id="form-${name}" name="${name}" type="${type}" value="${escape(value)}" ${extra}></div>`;

const selectField = (name, title, entries, selected = "") => `
  <div class="field"><label for="form-${name}">${escape(title)}</label>
  <select id="form-${name}" name="${name}">
    ${entries.map(([v, t]) => option(v, t, selected)).join("")}
  </select></div>`;

const formFooter = (text = "Save changes") => `
  <div class="error" id="form-error" role="alert"></div>
  <div class="modal-actions">
    <button class="btn" type="button" data-action="close-modal">Cancel</button>
    <button class="btn primary" type="submit">${escape(text)}</button>
  </div>`;

function bindForm(handler, success) {
  const form = modal.querySelector("form");
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const button = form.querySelector('[type="submit"]');
    button.disabled = true;
    form.querySelector("#form-error").textContent = "";
    try {
      await handler(Object.fromEntries(new FormData(form)), form);
      modal.close();
      state.detail = null;
      await reload();
      notify(success);
    } catch (error) {
      const target = form.querySelector("#form-error");
      if (target && modal.open) target.textContent = error.message;
      else notify(error.message);
    } finally {
      button.disabled = false;
    }
  });
}

async function patientForm(id = null) {
  if (!canManage()) return;
  const patient = id ? await api.patient(id, true) : {};
  const stages = [...new Set([...treatmentStages, patient.treatment_stage].filter(Boolean))];
  openModal(id ? "Edit patient" : "Add a new patient", `
    <form>
      <div class="form-grid">
        ${inputField("name", "Patient name", patient.name, "text", 'required maxlength="120"')}
        ${inputField("phone", "Phone number", patient.phone, "tel", 'required placeholder="+15551234567"')}
        ${selectField("preferred_language", "Preferred language", [["English", "English"], ["Tamil", "Tamil"], ["Telugu", "Telugu"]], patient.preferred_language || "English")}
        ${selectField("doctor_id", "Assigned doctor", state.doctors.map(d => [d.id, d.name]), patient.doctor_id || (state.doctors[0]?.id || ""))}
        ${selectField("treatment_stage", "Treatment stage", stages.map(s => [s, s]), patient.treatment_stage || stages[0])}
      </div>
      <label class="check">
        <input type="checkbox" name="whatsapp_opt_in" ${patient.whatsapp_opt_in ? "checked" : ""}>
        Patient has explicitly consented to WhatsApp reminders.
      </label>
      <p class="muted"><small>Use international E.164 format. Only opted-in patients receive WhatsApp reminders.</small></p>
      ${formFooter(id ? "Save patient" : "Create patient")}
    </form>`);
  bindForm(async (data, form) => {
    data.whatsapp_opt_in = form.elements.whatsapp_opt_in.checked;
    return id ? api.updatePatient(id, data) : api.createPatient(data);
  }, id ? "Patient updated." : "Patient added and assigned.");
}

async function followForm(patientIdValue = null, followId = null) {
  if (!canManage()) return;
  if (!state.patients.length) { notify("Add a patient before creating a follow-up."); return; }
  const follow = followId ? await api.followUp(followId) : {};
  openModal(followId ? "Edit follow-up" : "Create follow-up", `
    <form>
      ${!followId ? selectField("patient_id", "Patient",
        state.patients.map(p => [p.id, `${p.name} · ${p.doctor_name}`]),
        patientIdValue || state.patients[0].id)
        : `<p class="muted">${escape(follow.patient_name)} · ${escape(follow.doctor_name)}</p>`}
      <div class="form-grid">
        ${inputField("follow_up_date", "Follow-up date", follow.follow_up_date || state.dashboard.today, "date", "required")}
        ${inputField("follow_up_type", "Follow-up type", follow.follow_up_type || "", "text", 'required maxlength="100" placeholder="e.g. Treatment review"')}
      </div>
      <p class="muted"><small>Status is calculated and stored by the backend. A date change is recorded as RESCHEDULED and the previous date stays in the history.</small></p>
      ${formFooter(followId ? "Save follow-up" : "Create follow-up")}
    </form>`);
  bindForm(async data => {
    if (followId) return api.updateFollowUp(followId, data);
    return api.createFollowUp(data);
  }, followId ? "Follow-up updated." : "Follow-up created.");
}

function appointmentForm(id) {
  if (!canManage()) return;
  openModal("Record appointment", `
    <form>
      <div class="form-grid">
        ${inputField("appointment_date", "Appointment date", state.dashboard.today, "date", "required")}
        ${selectField("status", "Appointment status", [["SCHEDULED", "Scheduled"],
          ["ATTENDED", "Attended"], ["CANCELLED", "Cancelled"], ["NO_SHOW", "No-show"]], "ATTENDED")}
      </div>
      <div class="field"><label for="form-note">Appointment note</label>
        <textarea id="form-note" name="note" maxlength="1000"></textarea></div>
      ${formFooter("Record appointment")}
    </form>`);
  bindForm(data => api.addAppointment(id, data), "Appointment recorded in patient history.");
}

function showActivityDetail(id) {
  const event = state.activity.find(item => item.id === id);
  if (!event) return;
  let details = event.details;
  try { details = JSON.stringify(JSON.parse(details), null, 2); } catch {}
  openModal(label(event.action), `
    <div class="detail-grid">
      ${detailField("Actor", escape(event.actor_name))}
      ${detailField("Time", escape(timeLabel(event.created_at)))}
      ${detailField("Category", escape(label(event.category)))}
      ${detailField("Patient", escape(event.patient_name || "—"))}
    </div>
    <article class="history-item"><pre>${escape(details)}</pre></article>`);
}

async function reload({ polling = false } = {}) {
  if (!state.user) return;
  if (state.loading) { if (!polling) state.again = true; return; }
  state.loading = true;
  try {
    const [dashboard, patients, doctors, follows, requests, messages, events, activity] =
      await Promise.all([
        api.dashboard(), api.patients(), api.doctors(),
        api.followUps(serverFilters()), api.requests(), api.messages(),
        api.calendar(serverFilters()),
        state.user.role === "admin" ? api.activity() : Promise.resolve([]),
      ]);
    Object.assign(state, { dashboard, patients, doctors, follows, requests, messages, events, activity });
    if (!state.month) state.month = dashboard.today.slice(0, 7);

    if (!document.querySelector(".shell")) {
      renderShell();
    } else if (!(polling && document.activeElement?.matches("[data-filter]"))) {
      renderContent();
      const synced = document.querySelector(".topline > span:last-child");
      if (synced) synced.innerHTML = `<span class="live-dot"></span>Synced ${escape(timeLabel(dashboard.generated_at))}`;
    }

    if (polling && modal.open && state.detail) {
      const d = state.detail;
      if (d.kind === "patient") await showPatient(d.id, d.historyOnly, true);
      else await showFollow(d.id, true);
    }
  } catch (error) {
    if (error.status === 401) renderLogin();
    else notify(error.message);
  } finally {
    state.loading = false;
    if (state.again) { state.again = false; reload(); }
  }
}

async function openRemindersModal() {
  if (!canManage()) return;
  openModal("Send Bulk WhatsApp Reminders", '<div class="initial-loader">Evaluating recipient eligibility and preferred languages...</div>');
  
  const selectedIds = Array.from(state.selectedFollowUps);
  const selectAll = selectedIds.length === 0;

  try {
    const preview = await api.remindersPreview({
      follow_up_ids: selectedIds,
      select_all_eligible: selectAll,
    });

    const content = `
      <div class="notice">
        <strong>Simulation / Mock Mode Active:</strong> Real sending is disabled. Reminders will be logged as <code>MOCK_SENT</code> with simulated IDs without contacting Meta WhatsApp API.
      </div>

      <div class="preview-summary-grid">
        <div class="preview-summary-card">
          <small>Recipients Selected</small>
          <strong>${preview.total_selected}</strong>
        </div>
        <div class="preview-summary-card">
          <small>Eligible To Send</small>
          <strong>${preview.eligible_count}</strong>
        </div>
        <div class="preview-summary-card">
          <small>Skipped / Ineligible</small>
          <strong>${preview.ineligible_count}</strong>
        </div>
      </div>

      <h3 class="section-label">Preferred Language Breakdown</h3>
      <div class="preview-languages-grid">
        <div class="preview-lang-pill">English<strong>${preview.language_breakdown.English}</strong></div>
        <div class="preview-lang-pill">Tamil<strong>${preview.language_breakdown.Tamil}</strong></div>
        <div class="preview-lang-pill">Telugu<strong>${preview.language_breakdown.Telugu}</strong></div>
      </div>

      <label class="check" style="margin-bottom: 18px;">
        <input type="checkbox" id="dry-run-toggle">
        <strong>Dry-Run Test Mode</strong> (Simulates preview without saving message records)
      </label>

      <h3 class="section-label">Eligible Patients (${preview.eligible_count})</h3>
      ${!preview.eligible_items.length ? '<p class="muted">No eligible follow-ups in current selection.</p>' : `
        <div class="preview-scroll">
          ${preview.eligible_items.map(item => `
            <div class="preview-row">
              <div class="preview-row-details">
                <strong>${escape(item.patient_name)}</strong> <small>(${escape(item.phone)})</small>
                <div class="preview-row-message">${escape(item.message_preview)}</div>
              </div>
              <span class="badge ${escape(item.preferred_language)}">${escape(item.preferred_language)}</span>
            </div>`).join("")}
        </div>`}

      ${preview.skipped_items.length ? `
        <h3 class="section-label">Ineligible / Skipped (${preview.skipped_items.length})</h3>
        <div class="preview-scroll">
          ${preview.skipped_items.map(s => `
            <div class="preview-row">
              <strong>${escape(s.patient_name)}</strong>
              <small class="muted">${escape(s.reason)}</small>
            </div>`).join("")}
        </div>` : ""}

      <div class="modal-actions">
        <button class="btn" data-action="close-modal">Cancel</button>
        <button class="btn primary" id="confirm-send-btn" ${preview.eligible_count === 0 ? "disabled" : ""}>
          Confirm & Send Follow-up Reminders (${preview.eligible_count})
        </button>
      </div>
    `;

    openModal("Send Bulk WhatsApp Reminders", content);

    const confirmBtn = modal.querySelector("#confirm-send-btn");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async () => {
        confirmBtn.disabled = true;
        confirmBtn.textContent = "Processing reminders...";
        const dryRun = modal.querySelector("#dry-run-toggle")?.checked || false;
        try {
          const res = await api.remindersSend({
            follow_up_ids: selectedIds,
            select_all_eligible: selectAll,
            dry_run: dryRun,
            idempotency_key: "batch-" + Date.now(),
          });
          modal.close();
          state.selectedFollowUps.clear();
          await reload();
          if (res.dry_run) {
            notify(`Dry-run preview complete: ${res.sent_count} eligible, ${res.skipped_count} skipped.`);
          } else {
            notify(`Reminders processed: ${res.sent_count} queued/mock sent, ${res.skipped_count} skipped, ${res.failed_count} failed.`);
          }
        } catch (err) {
          notify(err.message);
          confirmBtn.disabled = false;
        }
      });
    }
  } catch (err) {
    openModal("Send Bulk WhatsApp Reminders", `<div class="error">${escape(err.message)}</div><div class="modal-actions"><button class="btn" data-action="close-modal">Close</button></div>`);
  }
}

async function handleAction(action, id, button) {
  switch (action) {
    case "logout": await api.logout(); renderLogin(); return;
    case "close-modal": modal.close(); state.detail = null; return;
    case "new-patient": return patientForm();
    case "edit-patient": return patientForm(id);
    case "new-follow": return followForm(id || null);
    case "edit-follow": return followForm(null, id);
    case "patient": return showPatient(id);
    case "history": return showPatient(id, true);
    case "follow": return showFollow(id);
    case "new-appointment": return appointmentForm(id);
    case "open-reminders": return openRemindersModal();
    case "select-all-eligible":
      state.follows.filter(f => f.whatsapp_opt_in && f.status !== "COMPLETED").forEach(f => state.selectedFollowUps.add(String(f.id)));
      renderContent();
      return;
    case "clear-selection":
      state.selectedFollowUps.clear();
      renderContent();
      return;
    case "complete-follow":
      if (!confirm("Mark this follow-up as completed? This is recorded permanently.")) return;
      await api.updateFollowUp(id, { status: "COMPLETED" });
      await reload();
      notify("Follow-up completed.");
      return showFollow(id);
    case "approve":
    case "reject":
      if (!confirm(`${action === "approve" ? "Approve" : "Reject"} this reschedule request?`)) return;
      button.disabled = true;
      await api[action](id);
      await reload();
      notify(`Reschedule request ${action === "approve" ? "approved" : "rejected"}.`);
      return;
    case "previous-month": return shiftMonth(-1);
    case "next-month": return shiftMonth(1);
    case "calendar-today": state.month = state.dashboard.today.slice(0, 7); return renderContent();
    case "reset-filters": state.filters = emptyFilters(); return reload();
    case "doctor-patients":
      state.filters = { ...emptyFilters(), doctor: String(id) };
      state.page = "patients";
      await reload();
      return renderShell();
    case "activity-detail": return showActivityDetail(id);
  }
}

document.addEventListener("click", async event => {
  const navigation = event.target.closest("[data-nav]");
  if (navigation && state.user) {
    state.page = navigation.dataset.nav;
    renderShell();
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button) return;
  try {
    await handleAction(button.dataset.action, button.dataset.id || null, button);
  } catch (error) {
    button.disabled = false;
    if (error.status === 401) renderLogin();
    else notify(error.message);
  }
});

document.addEventListener("change", event => {
  if (event.target.matches("[data-filter]")) {
    state.filters[event.target.dataset.filter] = event.target.value;
    reload();  // the backend applies the filter
  }
  if (event.target.id === "activity-filter") {
    state.activityFilter = event.target.value;
    renderContent();
  }
  if (event.target.classList.contains("follow-checkbox")) {
    const fid = String(event.target.dataset.id);
    if (event.target.checked) state.selectedFollowUps.add(fid);
    else state.selectedFollowUps.delete(fid);
    renderContent();
  }
  if (event.target.id === "select-all-visible") {
    if (event.target.checked) {
      state.follows.forEach(f => state.selectedFollowUps.add(String(f.id)));
    } else {
      state.selectedFollowUps.clear();
    }
    renderContent();
  }
});

modal.addEventListener("close", () => { state.detail = null; });

setInterval(() => { if (state.user && !document.hidden) reload({ polling: true }); }, 15000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.user) reload({ polling: true });
});

(async function boot() {
  try {
    state.user = await api.me();
    await reload();
  } catch {
    renderLogin();
  }
})();
