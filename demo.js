// ===================================================================================
// CONFIG: paste your EmailJS values here (EmailJS dashboard -> Email Services for the
// Service ID, Email Templates for the Template ID, Account -> General for the Public Key).
// These are EmailJS IDs, not passwords: never put a Gmail or app password in this file.
// With any of the three left empty, emails are stored as SIMULATED instead of sent.
// ===================================================================================
const EMAILJS = {
  serviceId: "",
  templateId: "",
  publicKey: "",
};
// Every real email from this demo goes to this one inbox, whatever address was typed.
const DEMO_RECIPIENT = "punyaa@yopmail.com";
// ===================================================================================

// Mirrors app.py / logic.py: same validation, honeypot, rate limit, statuses, escalation
// rules, follow-up rule and message limits. The static page has no server, so real email
// goes through EmailJS, which delivers from the connected Gmail account.
// The Python app also caps emails per recipient address; that protects strangers'
// inboxes, which can't happen here because every email goes to DEMO_RECIPIENT.
const MAX_EMAILS_PER_DAY = 50;
const STORAGE_KEY = "clubhouse-demo-v3";
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const ENQUIRY_TYPES = ["Membership", "Society day", "Event"];
const STATUSES = ["New", "Contacted", "Awaiting reply", "Escalated", "Booked", "Closed"];
const FILTERS = ["All", ...STATUSES, "Follow-up due"];
const KEEP_STATUS_ON_SEND = ["Escalated", "Booked", "Closed"];
const NAME_MAX_LEN = 100;
const MESSAGE_MAX_LEN = 1000;
const SUBJECT_MAX_LEN = 200;
const REPLY_MAX_LEN = 5000;
const NOTE_MAX_LEN = 500;
const ASSIGNEE_MAX_LEN = 100;
const MAX_MESSAGES = 5;
const FOLLOW_UP_DAYS = 2;
const DAY_MS = 24 * 60 * 60 * 1000;
const RATE_LIMIT_WINDOW_MS = 60 * 1000;
const RATE_LIMIT_MAX_SUBMISSIONS = 5;
const CLUB = "punyaa184@gmail.com";
const MANAGER = "manager@example.com";
const FOOTER = "Sent from a demo application. If this reached you by mistake, ignore it.";
const KIND_LABELS = { enquiry: "Enquiry", confirmation: "Confirmation", reply: "Reply",
  "follow-up": "Follow-up", "escalation-alert": "Escalation alert to manager (internal)" };

// name, email, type, message, days ago,
// status changes [[days after, status, note, assigned to, priority]], replies [[days after, text]]
const DEMO_ENQUIRIES = [
  ["Alice Brennan", "alice.brennan@example.com", "Membership", "Hi, I'd like to enquire about full membership rates for next season.", 0, [], []],
  ["Tom O'Carroll", "tom.ocarroll@example.com", "Society day", "We're looking to book a society day for 24 golfers in June.", 1, [], []],
  ["Fiona Walsh", "fiona.walsh@example.com", "Event", "Could you tell me about hosting a 40th birthday party at the clubhouse?", 3, [], []],
  ["Declan Murphy", "declan.murphy@example.com", "Membership", "What's included in junior membership this year?", 5,
    [[1, "Contacted", "Called and left a voicemail."]], []],
  ["Grace Kelly", "grace.kelly@example.com", "Society day", "Enquiring about a corporate golf day for 16 people in September.", 2,
    [[1, "Awaiting reply", "Automatic: reply sent to the enquirer."]],
    [[1, "Thanks for getting in touch. September works well - could you let us know your preferred date and whether you'd like lunch included?"]]],
  ["Liam Fitzgerald", "liam.fitzgerald@example.com", "Event", "Do you cater for wedding receptions on site?", 7,
    [[1, "Awaiting reply", "Automatic: reply sent to the enquirer."], [3, "Booked", "Deposit paid for 14 August."]],
    [[1, "Yes, we cater for receptions of up to 120 guests. Would you like to visit for a tour?"],
     [3, "Great to meet you both today. Your date of 14 August is now confirmed."]]],
  ["Niamh Byrne", "niamh.byrne@example.com", "Membership", "Is there a waiting list for family membership?", 6,
    [[1, "Awaiting reply", "Automatic: reply sent to the enquirer."], [4, "Closed", "Joined another club."]],
    [[1, "There's no waiting list at the moment - the application form is on our website. Let us know if you have any questions."]]],
  ["Sean Doyle", "sean.doyle@example.com", "Society day", "Our society was double-booked on 3 May and turned away at the first tee. We'd like a refund of the deposit.", 2,
    [[0, "Contacted", "Apologised by phone; he wants the deposit back."],
     [1, "Escalated", "Refund request for a double booking - needs manager approval.", "Club manager", "Urgent"]], []],
];

let state;
let submissionLog = [];
let currentFilter = "All";

const withFooter = body => `${body.trimEnd()}\n\n--\n${FOOTER}`;
const confirmation = (name, type) => ({
  subject: `We received your ${type} enquiry`,
  body: withFooter(`Hi ${name},\n\nThanks for your ${type} enquiry. A member of our team will be in touch soon.\n\nClubhouse`),
});

function addMessage(s, m) {
  const record = { id: s.nextEmailId++, ...m };
  s.emails.push(record);
  return record;
}

const sendingForReal = () =>
  Boolean(EMAILJS.publicKey && EMAILJS.serviceId && EMAILJS.templateId && window.emailjs);

// caps use real time (not the simulated clock), like the Python app
function capReached() {
  const today = new Date().toISOString().slice(0, 10);
  const sentToday = state.emails.filter(m => m.status === "sent" && (m.realAt || "").slice(0, 10) === today);
  if (sentToday.length >= MAX_EMAILS_PER_DAY) return "Daily email limit reached for this demo.";
  return null;
}

// Like send_email() in app.py: send one outbound email (or simulate it) and record the
// result on `record`. Never throws: the enquiry is already saved.
async function deliver(record) {
  record.realAt = new Date().toISOString();
  if (!sendingForReal()) { record.status = "simulated"; return record; }
  record.to = DEMO_RECIPIENT;  // fixed recipient: the demo never emails anyone else
  const capError = capReached();
  if (capError) { record.status = "skipped"; record.error = capError; return record; }
  try {
    await emailjs.send(EMAILJS.serviceId, EMAILJS.templateId, {
      to_email: record.to, subject: record.subject, message: record.body, reply_to: CLUB,
    }, { publicKey: EMAILJS.publicKey });
    record.status = "sent";
  } catch (err) {
    record.status = "failed";
    record.error = `${err && err.status ? err.status + " " : ""}${(err && (err.text || err.message)) || String(err)}`;
  }
  return record;
}

function deliveryText(record) {
  switch (record.status) {
    case "sent": return `Sent to ${record.to} from ${CLUB}. Check that inbox (and its spam folder).`;
    case "simulated": return "SIMULATED, not really sent.";
    case "skipped": return `not sent: ${record.error} Your enquiry is still saved.`;
    case "failed": return `not sent: ${record.error}`;
    default: return "sending…";
  }
}

// Like db.change_status: set the status and record it in the history.
function changeStatus(s, enquiry, status, at, note = "", assignedTo = "", priority = "Normal") {
  const escalated = status === "Escalated";
  s.history.push({ id: s.nextHistoryId++, enquiryId: enquiry.id, oldStatus: enquiry.status, newStatus: status,
    note: note || "", assignedTo: assignedTo || "", priority: escalated ? priority : "", changedAt: at });
  Object.assign(enquiry, { status, statusChangedAt: at,
    escalationReason: escalated ? note : "", assignedTo: escalated ? assignedTo : "", priority: escalated ? priority : "" });
}

function seedState() {
  const now = Date.now();
  const s = { nextId: 1, nextEmailId: 1, nextHistoryId: 1, dayOffset: 0, enquiries: [], emails: [], history: [] };
  DEMO_ENQUIRIES.forEach(([name, email, type, message, daysAgo, changes, replies]) => {
    const created = now - daysAgo * DAY_MS;
    const at = (days, minutes = 0) => new Date(created + days * DAY_MS + 3600e3 + minutes * 60e3).toISOString();
    const iso = new Date(created).toISOString();
    const e = { id: s.nextId++, name, email, type, message, status: "New", createdAt: iso, statusChangedAt: iso,
      escalationReason: "", assignedTo: "", priority: "" };
    s.enquiries.push(e);
    addMessage(s, { enquiryId: e.id, direction: "inbound", kind: "enquiry", from: email, to: CLUB, subject: `${type} enquiry`, body: message, sentAt: iso, status: "received" });
    addMessage(s, { enquiryId: e.id, direction: "outbound", kind: "confirmation", from: CLUB, to: email, ...confirmation(name, type), sentAt: iso, status: "simulated" });
    replies.forEach(([daysAfter, text]) => addMessage(s, {
      enquiryId: e.id, direction: "outbound", kind: "reply", from: CLUB, to: email,
      subject: `Re: Your ${type} enquiry`, body: withFooter(`Hi ${name},\n\n${text}\n\nBest regards,\nClubhouse`),
      sentAt: at(daysAfter), status: "simulated",
    }));
    changes.forEach(([daysAfter, status, note, assignedTo, priority]) =>
      changeStatus(s, e, status, at(daysAfter, 1), note, assignedTo, priority));
  });
  return s;
}

function loadState() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) return JSON.parse(saved);
  } catch (e) { /* storage unavailable: fall back to in-memory */ }
  return seedState();
}

function saveState() {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) {}
}

const simulatedNow = () => new Date(Date.now() + state.dayOffset * DAY_MS);
const getEnquiry = id => state.enquiries.find(e => e.id === id);
const conversation = id => state.emails.filter(m => m.enquiryId === id);
const historyFor = id => state.history.filter(h => h.enquiryId === id)
  .sort((a, b) => b.changedAt.localeCompare(a.changedAt) || b.id - a.id);
// failed or skipped attempts don't count toward the per-enquiry limit
const messagesUsed = id => conversation(id).filter(m =>
  (m.kind === "reply" || m.kind === "follow-up") && ["sent", "simulated"].includes(m.status)).length;
const needsNote = (oldStatus, newStatus) => newStatus === "Escalated" || oldStatus === "Escalated";

function isFollowUpDue(enquiry, now) {
  if (enquiry.status !== "New") return false;
  return now - new Date(enquiry.createdAt) >= FOLLOW_UP_DAYS * DAY_MS;
}

function isRateLimited() {
  const now = Date.now();
  submissionLog = submissionLog.filter(t => now - t < RATE_LIMIT_WINDOW_MS);
  return submissionLog.length >= RATE_LIMIT_MAX_SUBMISSIONS;
}

const hasLineBreak = v => /[\r\n]/.test(v);

function validateEnquiry(form) {
  const errors = {};
  const name = form.name.trim();
  const email = form.email.trim();
  const message = form.message.trim();
  if (!name) errors.name = "Please enter your name.";
  else if (hasLineBreak(name)) errors.name = "Your name can't contain line breaks.";
  else if (name.length > NAME_MAX_LEN) errors.name = `Name must be under ${NAME_MAX_LEN} characters.`;
  if (!email) errors.email = "Please enter your email address.";
  else if (!EMAIL_RE.test(email)) errors.email = "Please enter a valid email address.";
  if (!ENQUIRY_TYPES.includes(form.enquiry_type)) errors.enquiry_type = "Please choose an enquiry type.";
  if (!message) errors.message = "Please enter a message.";
  else if (message.length > MESSAGE_MAX_LEN) errors.message = `Message must be under ${MESSAGE_MAX_LEN} characters.`;
  return errors;
}

function validateReply(subject, body) {
  const errors = {};
  if (!subject) errors.subject = "Please enter a subject.";
  else if (hasLineBreak(subject)) errors.subject = "The subject can't contain line breaks.";
  else if (subject.length > SUBJECT_MAX_LEN) errors.subject = `Subject must be under ${SUBJECT_MAX_LEN} characters.`;
  if (!body) errors.body = "Please write a message.";
  else if (body.length > REPLY_MAX_LEN) errors.body = "Message must be under 5,000 characters.";
  return errors;
}

function validateStatusChange(oldStatus, v) {
  const errors = {};
  if (needsNote(oldStatus, v.status) && !v.note) {
    errors.note = v.status === "Escalated" ? "Please give a reason for escalating."
      : "Please add a short note, for example why it is resolved.";
  } else if (v.note.length > NOTE_MAX_LEN) errors.note = `Keep the note under ${NOTE_MAX_LEN} characters.`;
  if (v.status === "Escalated" && v.assignedTo.length > ASSIGNEE_MAX_LEN)
    errors.assigned_to = `Keep this under ${ASSIGNEE_MAX_LEN} characters.`;
  return errors;
}

const fmtDate = iso => new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
const fmtDateTime = iso => new Date(iso).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
const esc = s => String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const statusBadge = s => s === "Escalated"
  ? `<span class="badge badge-status badge-Escalated"><span aria-hidden="true">⚠</span> Escalated</span>`
  : `<span class="badge badge-status badge-${s.replace(/ /g, "-")}">${esc(s)}</span>`;
const escalationDetails = e => e.status !== "Escalated" ? "" :
  (e.priority === "Urgent" ? ' <span class="badge badge-urgent">Urgent</span>' : "") +
  (e.assignedTo ? ` <span class="muted">&rarr; ${esc(e.assignedTo)}</span>` : "");
const deliveryBadge = m => `<span class="badge badge-${m.status}">${m.status.toUpperCase()}</span>`;
const statusSelect = e => `<label class="sr-only" for="status-${e.id}">Status for ${esc(e.name)}</label>
  <select id="status-${e.id}" data-status="${e.id}">${STATUSES.map(s =>
    `<option${s === e.status ? " selected" : ""}>${esc(s)}</option>`).join("")}</select>`;

// --- form ---
const formEl = document.getElementById("enquiry-form");
const formError = document.getElementById("form-error");

function showErrors(attr, errors) {
  document.querySelectorAll(`[${attr}]`).forEach(p => {
    const msg = errors[p.getAttribute(attr)];
    p.textContent = msg || "";
    p.hidden = !msg;
  });
}

formEl.addEventListener("submit", e => {
  e.preventDefault();
  const data = Object.fromEntries(new FormData(formEl));
  data.enquiry_type = data.enquiry_type || "";
  formError.hidden = true;

  // honeypot: silently drop, like the server does
  if (data.website) { formEl.reset(); showErrors("data-error", {}); return; }

  if (isRateLimited()) {
    formError.textContent = "Too many submissions. Please try again in a minute.";
    formError.hidden = false;
    return;
  }

  const errors = validateEnquiry(data);
  showErrors("data-error", errors);
  if (Object.keys(errors).length) return;

  submissionLog.push(Date.now());
  const at = simulatedNow().toISOString();
  const name = data.name.trim();
  const email = data.email.trim();
  const id = state.nextId++;
  state.enquiries.push({ id, name, email, type: data.enquiry_type, message: data.message.trim(),
    status: "New", createdAt: at, statusChangedAt: at, escalationReason: "", assignedTo: "", priority: "" });
  addMessage(state, { enquiryId: id, direction: "inbound", kind: "enquiry", from: email, to: CLUB,
    subject: `${data.enquiry_type} enquiry`, body: data.message.trim(), sentAt: at, status: "received" });
  const record = addMessage(state, { enquiryId: id, direction: "outbound", kind: "confirmation", from: CLUB, to: email,
    ...confirmation(name, data.enquiry_type), sentAt: at, status: "sending" });
  saveState();

  formEl.reset();
  document.getElementById("thanks-email").textContent = email;
  const thanksDelivery = document.getElementById("thanks-delivery");
  thanksDelivery.textContent = deliveryText(record);
  location.hash = "#thanks";
  deliver(record).then(() => {
    saveState();
    thanksDelivery.textContent = deliveryText(record);
    thanksDelivery.style.color = record.status === "sent" ? "var(--ok)"
      : ["failed", "skipped"].includes(record.status) ? "var(--error)" : "";
  });
});

// --- staff ---
function renderStaff() {
  const now = simulatedNow();
  let rows = [...state.enquiries].sort((a, b) => b.createdAt.localeCompare(a.createdAt) || b.id - a.id);
  const due = rows.filter(e => isFollowUpDue(e, now)).length;
  const escalated = rows.filter(e => e.status === "Escalated").length;
  if (currentFilter === "Follow-up due") rows = rows.filter(e => isFollowUpDue(e, now));
  else if (currentFilter !== "All") rows = rows.filter(e => e.status === currentFilter);
  // escalated (urgent first), then overdue; the sort is stable so newest-first holds within each group
  const rank = e => [e.status !== "Escalated", e.priority !== "Urgent", !isFollowUpDue(e, now)];
  rows.sort((a, b) => { const ra = rank(a), rb = rank(b); for (let i = 0; i < 3; i++) if (ra[i] !== rb[i]) return ra[i] - rb[i]; return 0; });

  document.getElementById("escalated-count").textContent = escalated;
  document.getElementById("follow-up-count").textContent = due;
  document.getElementById("follow-up-label").textContent = due === 1 ? "follow-up" : "follow-ups";
  const off = state.dayOffset;
  document.getElementById("sim-time").textContent =
    `Simulated date: ${fmtDate(now.toISOString())} (offset: ${off} day${off === 1 ? "" : "s"})`;

  document.getElementById("filters").innerHTML = FILTERS.map(f =>
    `<button type="button" data-filter="${esc(f)}" aria-pressed="${f === currentFilter}">${esc(f)}</button>`).join("");

  const tbody = document.getElementById("enquiry-rows");
  tbody.innerHTML = rows.length ? rows.map(e => `
    <tr>
      <td><a href="#staff/${e.id}">${esc(e.name)}</a><br><span class="muted">${esc(e.email)}</span></td>
      <td>${esc(e.type)}</td>
      <td>${statusBadge(e.status)}${escalationDetails(e)}${isFollowUpDue(e, now) ? '<span class="badge badge-due">Follow-up due</span>' : ""}
        <br><span class="muted">since ${fmtDate(e.statusChangedAt)}</span></td>
      <td>${fmtDate(e.createdAt)}</td>
      <td><div class="row-actions">${statusSelect(e)}
        ${e.status !== "Escalated" ? `<a class="btn btn-small btn-escalate" href="#staff/${e.id}/escalate">Escalate</a>` : ""}
        ${isFollowUpDue(e, now) ? `<a class="btn btn-small" href="#staff/${e.id}/follow-up">Send follow-up</a>` : ""}</div></td>
    </tr>`).join("") : `<tr><td colspan="5">No enquiries match this filter.</td></tr>`;
}

document.getElementById("filters").addEventListener("click", e => {
  if (!e.target.dataset.filter) return;
  currentFilter = e.target.dataset.filter;
  renderStaff();
});

// staff-list dropdowns save on change, except escalating or leaving Escalated, which
// opens the detail page's status form for the required note
document.getElementById("enquiry-rows").addEventListener("change", e => {
  const id = Number(e.target.dataset.status);
  if (!id) return;
  const enquiry = getEnquiry(id);
  if (needsNote(enquiry.status, e.target.value)) {
    pendingStatus = e.target.value;
    location.hash = `#staff/${id}/status`;
    return;
  }
  if (e.target.value !== enquiry.status) changeStatus(state, enquiry, e.target.value, simulatedNow().toISOString());
  saveState();
  renderStaff();
});

document.getElementById("advance-day").addEventListener("click", () => {
  state.dayOffset += 1; saveState(); renderStaff();
});
document.getElementById("reset-time").addEventListener("click", () => {
  state.dayOffset = 0; saveState(); renderStaff();
});

// --- detail: status, timeline, compose, history ---
let detailId = null;
let composeKind = "reply";
let pendingStatus = null;

function composeDefaults(e, kind) {
  return kind === "follow-up"
    ? { subject: "Following up on your enquiry",
        body: `Hi ${e.name},\n\nI'm following up on your ${e.type.toLowerCase()} enquiry. Do you still need help with it? Just reply to this email and we'll be happy to help, or let us know a good time to call you.\n\nBest regards,\nClubhouse` }
    : { subject: `Re: Your ${e.type} enquiry`, body: `Hi ${e.name},\n\n\n\nBest regards,\nClubhouse` };
}

function showStatusFields(e) {
  const chosen = document.getElementById("status-select").value;
  document.getElementById("escalation-fields").hidden = chosen !== "Escalated";
  document.getElementById("status-note-label").textContent =
    chosen === "Escalated" ? "Reason for escalating (required)"
      : e.status === "Escalated" ? "Note: why is it no longer escalated? (required)" : "Note (optional)";
  document.getElementById("status-save").textContent =
    chosen === "Escalated" && e.status !== "Escalated" ? "Escalate" : "Save status";
  document.getElementById("escalate-btn").hidden = chosen === "Escalated" || e.status === "Escalated";
}

function renderDetail(id, { keepForm = false } = {}) {
  const e = getEnquiry(id);
  if (!e) { location.hash = "#staff"; return; }
  detailId = id;
  const due = isFollowUpDue(e, simulatedNow());
  document.getElementById("detail-head").innerHTML = `
    <h1>${esc(e.name)}</h1>
    <p class="muted">${esc(e.email)} &middot; ${esc(e.type)} &middot; submitted ${fmtDate(e.createdAt)}</p>
    <p>${statusBadge(e.status)}${escalationDetails(e)}${due ? '<span class="badge badge-due">Follow-up due</span>' : ""}
      <span class="muted">status changed ${fmtDateTime(e.statusChangedAt)}</span></p>
    ${e.status === "Escalated" && e.escalationReason ? `<p><strong>Reason:</strong> ${esc(e.escalationReason)}</p>` : ""}`;

  if (!keepForm) {
    document.getElementById("status-select").innerHTML =
      STATUSES.map(s => `<option${s === (pendingStatus || e.status) ? " selected" : ""}>${esc(s)}</option>`).join("");
    document.getElementById("status-note").value = "";
    document.getElementById("status-assigned").value = e.assignedTo || "";
    document.getElementById("status-priority").value = e.priority || "Normal";
    showErrors("data-status-error", {});
    pendingStatus = null;
  }
  showStatusFields(e);

  // emails and internal notes, oldest first
  const items = [
    ...conversation(id).map(m => ({ at: m.sentAt, order: [0, m.id], html: `
      <li class="card ${m.direction}">
        <p class="muted"><strong>${KIND_LABELS[m.kind] || esc(m.kind)}</strong> &middot;
          ${m.direction === "inbound" ? `from <strong>${esc(m.from)}</strong>` : `to <strong>${esc(m.to)}</strong>`}
          &middot; ${fmtDateTime(m.sentAt)} &middot; ${deliveryBadge(m)}</p>
        <strong>${esc(m.subject)}</strong>
        <pre>${esc(m.body)}</pre>
      </li>` })),
    ...historyFor(id).map(h => ({ at: h.changedAt, order: [1, h.id], html: `
      <li class="card note">
        <p class="muted"><strong>Internal note</strong> (not emailed) &middot; ${fmtDateTime(h.changedAt)}</p>
        Status: ${esc(h.oldStatus || "—")} &rarr; ${statusBadge(h.newStatus)}
        ${h.priority === "Urgent" ? '<span class="badge badge-urgent">Urgent</span>' : ""}
        ${h.assignedTo ? `<span class="muted">&rarr; ${esc(h.assignedTo)}</span>` : ""}
        ${h.note ? `<pre>${esc(h.note)}</pre>` : ""}
      </li>` })),
  ].sort((a, b) => a.at.localeCompare(b.at) || a.order[0] - b.order[0] || a.order[1] - b.order[1]);
  document.getElementById("thread").innerHTML = items.map(i => i.html).join("");

  const history = historyFor(id);
  document.getElementById("history").innerHTML = history.length ? history.map(h => `
    <li><span class="muted">${fmtDateTime(h.changedAt)}</span> ${esc(h.oldStatus || "—")} &rarr; <strong>${esc(h.newStatus)}</strong>
      ${h.priority === "Urgent" ? '<span class="badge badge-urgent">Urgent</span>' : ""}
      ${h.assignedTo ? `<span class="muted">assigned to ${esc(h.assignedTo)}</span>` : ""}
      ${h.note ? `<br>${esc(h.note)}` : ""}</li>`).join("") : `<li class="muted">No status changes yet.</li>`;

  const left = MAX_MESSAGES - messagesUsed(id);
  const label = composeKind === "follow-up" ? "Follow-up" : "Reply";
  document.getElementById("reply-heading").textContent = label;
  document.querySelectorAll("[data-compose]").forEach(b =>
    b.className = "btn " + (b.dataset.compose === composeKind ? "btn-primary" : "btn-secondary"));
  document.getElementById("reply-submit").textContent = `Send ${label.toLowerCase()}`;
  document.getElementById("reply-limit").hidden = left > 0;
  document.getElementById("reply-form").hidden = left <= 0;
  document.getElementById("replies-left").textContent = `${left} of ${MAX_MESSAGES} replies and follow-ups left for this enquiry.`;
  document.getElementById("reply-to").value = e.email;
  if (!keepForm) {
    const d = composeDefaults(e, composeKind);
    document.getElementById("reply-subject").value = d.subject;
    document.getElementById("reply-body").value = d.body;
    document.getElementById("reply-error").hidden = true;
    showErrors("data-reply-error", {});
  }
}

document.getElementById("status-select").addEventListener("change", () => showStatusFields(getEnquiry(detailId)));
document.getElementById("escalate-btn").addEventListener("click", () => {
  document.getElementById("status-select").value = "Escalated";
  showStatusFields(getEnquiry(detailId));
  document.getElementById("status-note").focus();
});

document.getElementById("status-form").addEventListener("submit", ev => {
  ev.preventDefault();
  const e = getEnquiry(detailId);
  const v = {
    status: document.getElementById("status-select").value,
    note: document.getElementById("status-note").value.trim(),
    assignedTo: document.getElementById("status-assigned").value.trim(),
    priority: document.getElementById("status-priority").value,
  };
  if (!STATUSES.includes(v.status)) return;
  if (v.status === e.status && v.status !== "Escalated") return;
  const errors = validateStatusChange(e.status, v);
  showErrors("data-status-error", errors);
  if (Object.keys(errors).length) return;  // typed text stays in the form
  const at = simulatedNow().toISOString();
  changeStatus(state, e, v.status, at, v.note, v.assignedTo, v.priority);
  let message = `Status changed to ${v.status}.`;
  if (v.status === "Escalated") {
    const reasonLine = v.note.split(/\s+/).join(" ");
    addMessage(state, { enquiryId: e.id, direction: "outbound", kind: "escalation-alert", from: CLUB, to: MANAGER,
      subject: `Enquiry escalated: ${e.name}, ${reasonLine}`.slice(0, SUBJECT_MAX_LEN),
      body: withFooter(`Enquiry escalated: ${e.name}, ${reasonLine}\n\nPriority: ${v.priority}\nAssigned to: ${v.assignedTo || "not assigned"}\nEnquiry: ${e.type} from ${e.email}\n\nReason:\n${v.note}\n\nClubhouse`),
      sentAt: at, status: "simulated" });
    message = `${e.name} escalated. Manager alert to ${MANAGER}: SIMULATED, not really sent.`;
  }
  saveState();
  renderDetail(e.id);
  const flash = document.getElementById("status-flash");
  flash.textContent = message;
  flash.hidden = false;
});

document.querySelectorAll("[data-compose]").forEach(b => b.addEventListener("click", () => {
  composeKind = b.dataset.compose;
  renderDetail(detailId, { keepForm: false });
}));

document.getElementById("reply-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const e = getEnquiry(detailId);
  const subject = document.getElementById("reply-subject").value.trim();
  const body = document.getElementById("reply-body").value.trim();
  const errors = validateReply(subject, body);
  showErrors("data-reply-error", errors);
  const replyError = document.getElementById("reply-error");
  replyError.hidden = true;
  if (Object.keys(errors).length) return;
  if (messagesUsed(e.id) >= MAX_MESSAGES) {
    replyError.textContent = `This enquiry already has ${MAX_MESSAGES} replies and follow-ups, the most this demo allows.`;
    replyError.hidden = false;
    return;
  }
  const kind = composeKind;
  const label = kind === "follow-up" ? "Follow-up" : "Reply";
  const at = simulatedNow().toISOString();
  const submit = document.getElementById("reply-submit");
  submit.disabled = true;
  submit.textContent = "Sending…";
  // always the address that submitted the enquiry
  const record = addMessage(state, { enquiryId: e.id, direction: "outbound", kind, from: CLUB, to: e.email,
    subject, body: withFooter(body), sentAt: at, status: "sending" });
  await deliver(record);
  submit.disabled = false;
  saveState();

  if (record.status === "failed" || record.status === "skipped") {
    // keep the draft so it can be retried
    renderDetail(e.id, { keepForm: true });
    replyError.textContent = `Your ${label.toLowerCase()} was not sent: ${record.error} Your text is kept below.`;
    replyError.hidden = false;
    return;
  }
  if (!KEEP_STATUS_ON_SEND.includes(e.status) && e.status !== "Awaiting reply")
    changeStatus(state, e, "Awaiting reply", at, `Automatic: ${label.toLowerCase()} sent to the enquirer.`);
  saveState();
  renderDetail(e.id);
  const flash = document.getElementById("reply-flash");
  flash.textContent = record.status === "sent"
    ? `Sent: ${label.toLowerCase()} emailed to ${record.to} from ${CLUB}. Replies will arrive in that Gmail inbox.`
    : `${label} to ${e.email} saved as SIMULATED, not really sent.`;
  flash.hidden = false;
});

// --- email log ---
function renderEmails() {
  const list = document.getElementById("email-list");
  const emails = [...state.emails].sort((a, b) => b.sentAt.localeCompare(a.sentAt) || b.id - a.id);
  list.innerHTML = emails.length ? emails.map(m => `
    <div class="card ${m.direction}">
      <p class="muted">${m.direction === "inbound" ? "Inbound" : "Outbound"} &middot; ${KIND_LABELS[m.kind] || esc(m.kind)} &middot;
        From <strong>${esc(m.from)}</strong> to <strong>${esc(m.to)}</strong> &middot; ${fmtDateTime(m.sentAt)} &middot; ${deliveryBadge(m)}</p>
      <a href="#staff/${m.enquiryId}"><strong>${esc(m.subject)}</strong></a>
      <pre class="email-body">${esc(m.body)}</pre>
    </div>`).join("")
    : `<div class="card">No emails yet. <a href="#form">Submit an enquiry</a> to see one appear here.</div>`;
}

document.getElementById("reset-demo").addEventListener("click", () => {
  state = seedState(); currentFilter = "All"; detailId = null; saveState(); route();
});

// --- routing: #form #thanks #staff #emails #staff/<id>[/follow-up|/escalate|/status] ---
const VIEWS = ["form", "thanks", "staff", "detail", "emails"];
function route() {
  const hash = location.hash.slice(1);
  let view = hash;
  const detailMatch = hash.match(/^staff\/(\d+)(?:\/(follow-up|escalate|status))?$/);
  if (detailMatch) view = "detail";
  if (!VIEWS.includes(view)) view = "form";
  if (view === "thanks" && !document.getElementById("thanks-email").textContent) view = "form";
  VIEWS.forEach(v => { document.getElementById(`view-${v}`).hidden = v !== view; });
  const navView = view === "detail" ? "staff" : view;
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("active", a.dataset.view === navView));
  if (view === "staff") renderStaff();
  if (view === "detail") {
    const id = Number(detailMatch[1]);
    const action = detailMatch[2];
    if (action === "escalate") pendingStatus = "Escalated";
    const sameEnquiry = id === detailId;
    if (!sameEnquiry || action === "follow-up") composeKind = action === "follow-up" ? "follow-up" : "reply";
    renderDetail(id, { keepForm: sameEnquiry && !action });
    if (action === "follow-up") document.getElementById("reply-heading").scrollIntoView?.();
    if (action === "escalate" || action === "status") document.getElementById("status-note").focus();
  }
  if (view === "emails") renderEmails();
}

window.addEventListener("hashchange", () => {
  document.getElementById("reply-flash").hidden = true;
  document.getElementById("status-flash").hidden = true;
  window.scrollTo(0, 0);
  route();
});

state = loadState();
if (sendingForReal()) {
  document.getElementById("mode-banner").innerHTML =
    `<strong>Real emails:</strong> confirmations, replies and follow-ups are sent from ${CLUB} ` +
    `to the demo inbox ${DEMO_RECIPIENT} only. Enquiries are stored in this browser only.`;
  document.getElementById("compose-mode").innerHTML =
    `Sent as a real email from <strong>${CLUB}</strong> to the demo inbox <strong>${DEMO_RECIPIENT}</strong>. ` +
    `Replies arrive in the ${CLUB} Gmail inbox.`;
}
route();
