"use strict";

const $ = (id) => document.getElementById(id);
let state = { items: [], requests: [], events: [] };
let selected = null;
let busy = false;
let uncertainCommand = null;
const decisionDrafts = new Map();
const labels = { pending: "Pending", approved: "Approved / out", declined: "Declined", returned: "Returned", requested: "Requested" };

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function announce(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "notice error" : "notice";
  $("notice").hidden = false;
}

function markBusy(value) {
  busy = value;
  document.querySelectorAll("button").forEach((button) => { button.disabled = value; });
  $("workspace").setAttribute("aria-busy", String(value));
  $("request-form").setAttribute("aria-busy", String(value));
}

async function fetchJSON(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal, cache: "no-store" });
    const data = await response.json();
    if (!response.ok) {
      const error = new Error(data.error?.message || "The server could not complete this action.");
      error.code = data.error?.code;
      error.status = response.status;
      throw error;
    }
    return data;
  } finally { clearTimeout(timer); }
}

async function loadState() {
  const data = await fetchJSON("/api/state");
  state = data;
  if (!state.requests.some((request) => request.id === selected)) {
    selected = state.requests.find((request) => request.status === "pending")?.id ?? state.requests[0]?.id ?? null;
  }
  renderInventory();
  renderRows();
  renderDetail();
  renderItemOptions();
  $("updated").textContent = "Updated " + new Date(data.read_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function renderInventory() {
  const list = $("inventory");
  list.replaceChildren();
  if (!state.items.length) {
    list.append(element("li", "empty-state", "No equipment has been seeded. Stop the server, run python app.py seed, and start it again."));
    return;
  }
  for (const item of state.items) {
    const row = element("li");
    row.append(element("h3", "", item.name), element("p", "item-category", item.category));
    const line = element("div", "stock-line");
    line.append(element("strong", "", `${item.available} of ${item.total} free`), element("span", "muted", `${item.held} out`));
    const ruler = element("div", "ruler");
    ruler.setAttribute("aria-hidden", "true");
    for (let index = 0; index < item.total; index++) ruler.append(element("span", index < item.available ? "free" : ""));
    row.append(line, ruler);
    list.append(row);
  }
}

function filteredRequests() {
  const query = $("search").value.trim().toLocaleLowerCase();
  const status = $("status-filter").value;
  return state.requests.filter((request) => (status === "all" || request.status === status)
    && `${request.person} ${request.item_name} ${request.purpose} ${request.id}`.toLocaleLowerCase().includes(query))
    .sort((a, b) => Number(b.status === "pending") - Number(a.status === "pending") || b.id - a.id);
}

function badge(status) { return element("span", `status ${status}`, labels[status]); }

function renderRows() {
  const rows = $("request-rows");
  rows.replaceChildren();
  const requests = filteredRequests();
  $("queue-count").textContent = String(requests.length);
  $("empty-queue").hidden = requests.length > 0;
  $("empty-queue").textContent = state.requests.length ? "No requests match these filters. Change the status or clear the search." : "No requests yet. Use New request to borrow equipment.";
  for (const request of requests) {
    const row = element("tr", request.id === selected ? "selected" : "");
    const nameCell = element("td");
    const button = element("button", "row-button", request.person);
    button.type = "button";
    button.disabled = busy;
    button.setAttribute("aria-label", `Review request ${request.id}: ${request.person}, ${request.item_name}`);
    button.setAttribute("aria-pressed", String(request.id === selected));
    button.addEventListener("click", () => {
      selected = request.id;
      renderRows();
      renderDetail();
      $("detail-title").focus({ preventScroll: true });
      if (window.matchMedia("(max-width: 800px)").matches) $("detail-title").scrollIntoView({ block: "start" });
    });
    nameCell.append(button, element("div", "row-item", request.item_name));
    const statusCell = element("td");
    statusCell.append(badge(request.status));
    row.append(nameCell, element("td", "numeric", String(request.quantity)), statusCell);
    rows.append(row);
  }
}

function fact(label, value, wide = false) {
  const group = element("div", wide ? "wide" : "");
  group.append(element("dt", "", label), element("dd", "", value));
  return group;
}

function renderDetail() {
  const detail = $("detail-body");
  detail.replaceChildren();
  const request = state.requests.find((candidate) => candidate.id === selected);
  $("detail-id").textContent = request ? `#${String(request.id).padStart(3, "0")} · v${request.version}` : "";
  if (!request) {
    detail.append(element("p", "empty-state", "Select a request to review the equipment, decision, and history."));
    return;
  }
  detail.append(element("h3", "detail-name", request.person), badge(request.status));
  const summary = element("dl", "request-summary");
  summary.append(fact("Equipment", request.item_name), fact("Quantity", `${request.quantity} ${request.quantity === 1 ? "unit" : "units"}`), fact("Purpose", request.purpose, true));
  detail.append(summary);
  const item = state.items.find((candidate) => candidate.id === request.item_id);
  if (request.status === "pending") {
    const sufficient = item.available >= request.quantity;
    detail.append(element("p", `availability-note${sufficient ? "" : " warning"}`, sufficient
      ? `${item.available} available now. Approval will reserve ${request.quantity} and leave ${item.available - request.quantity} free.`
      : `${item.available} available now; ${request.quantity} requested. This request can wait until equipment returns, or be declined.`));
  }
  if (["pending", "approved"].includes(request.status)) {
    const label = element("label", "decision-label", request.status === "approved" ? "Return note (optional)" : "Decision note (required to decline)");
    const note = element("textarea");
    note.id = "decision-note";
    note.maxLength = 240;
    note.rows = 2;
    note.value = decisionDrafts.get(request.id) || "";
    note.placeholder = request.status === "approved" ? "e.g. All pieces checked and received" : "Add context for the next review";
    note.addEventListener("input", () => decisionDrafts.set(request.id, note.value));
    label.append(note);
    detail.append(label);
    const actions = element("div", "decision-actions");
    const operations = request.status === "pending" ? [["approve", "Approve request", "primary"], ["decline", "Decline", "danger"]] : [["return", "Mark all returned", "return"]];
    for (const [operation, title, className] of operations) {
      const button = element("button", className, title);
      button.type = "button";
      button.disabled = busy;
      button.addEventListener("click", () => {
        if (operation === "decline" && !note.value.trim()) {
          announce("Add a short reason in the decision note before declining.", true);
          note.focus();
          return;
        }
        issueCommand(operation, { request_id: request.id, expected_version: request.version, note: note.value.trim() });
      });
      actions.append(button);
    }
    detail.append(actions, element("p", "detail-help", request.status === "approved" ? "Confirm that every unit is back. Partial returns are not supported." : "Availability is checked again when you approve."));
  } else detail.append(element("p", "availability-note", request.status === "returned" ? "Equipment returned. This request no longer holds any stock." : "Request closed. No equipment was reserved."));
  const history = element("section", "history");
  history.append(element("h3", "", "Request history"));
  const timeline = element("ol", "timeline");
  for (const event of state.events.filter((candidate) => candidate.request_id === request.id)) {
    const row = element("li");
    const line = element("div", "event-line");
    const time = element("time", "", new Date(event.happened_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }));
    time.dateTime = event.happened_at;
    line.append(element("strong", "", labels[event.action] || event.action), time);
    row.append(line, element("p", "event-note", event.note));
    timeline.append(row);
  }
  history.append(timeline);
  detail.append(history);
}

function renderItemOptions() {
  const prior = $("item").value;
  $("item").replaceChildren();
  for (const item of state.items) {
    const option = element("option", "", `${item.name} (${item.available} free)`);
    option.value = String(item.id);
    $("item").append(option);
  }
  if (state.items.some((item) => String(item.id) === prior)) $("item").value = prior;
  updateQuantityHelp();
}

function updateQuantityHelp() {
  const item = state.items.find((candidate) => String(candidate.id) === $("item").value);
  $("quantity").max = String(item?.total ?? 1);
  $("quantity-help").textContent = item ? `${item.total} owned; ${item.available} available now. Approval reserves equipment.` : "Seed the inventory before creating a request.";
}

function openForm(open) {
  $("request-form-panel").hidden = !open;
  $("new-request").setAttribute("aria-expanded", String(open));
  if (open) $("person").focus();
  else $("new-request").focus({ preventScroll: true });
}

async function issueCommand(operation, payload, retry = null) {
  if (busy) return;
  if (uncertainCommand && !retry) {
    announce("First retry the unconfirmed command above. Its original details have been kept so the result can be checked safely.", true);
    $("retry-command").focus();
    return;
  }
  const command = retry || { command_id: crypto.randomUUID(), operation, payload };
  markBusy(true);
  try {
    const result = await fetchJSON("/api/commands", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(command) });
    uncertainCommand = null;
    $("recovery").hidden = true;
    selected = result.request.id;
    decisionDrafts.delete(selected);
    if (command.operation === "create") {
      $("request-form").reset();
      openForm(false);
    }
    const successes = { create: "Request submitted. It is pending review.", approve: "Request approved. Equipment is reserved.", decline: "Request declined. Your reason is in its history.", return: "Return recorded. Equipment is available again." };
    announce(result.replayed ? "This command was already saved. No duplicate change was made." : successes[command.operation]);
    try { await loadState(); }
    catch { announce("Your change was saved, but the latest workspace could not load. Use Refresh before making another decision.", true); }
  } catch (error) {
    if (!error.status || error.status >= 500) {
      uncertainCommand = command;
      $("recovery").hidden = false;
      announce(error.status ? error.message : "The server response could not be confirmed. Check that the server is running, then retry the same command.", true);
    } else {
      uncertainCommand = null;
      $("recovery").hidden = true;
      announce(error.message, true);
      if (error.status === 409) {
        try { await loadState(); } catch { /* Keep conflict and the user's note visible. */ }
      }
    }
  } finally { markBusy(false); }
}

$("request-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!$("request-form").reportValidity()) return;
  issueCommand("create", { person: $("person").value.trim(), item_id: Number($("item").value), quantity: Number($("quantity").value), purpose: $("purpose").value.trim() });
});
$("new-request").addEventListener("click", () => openForm($("request-form-panel").hidden));
$("close-form").addEventListener("click", () => openForm(false));
$("search").addEventListener("input", renderRows);
$("status-filter").addEventListener("change", renderRows);
$("item").addEventListener("change", updateQuantityHelp);
$("retry-command").addEventListener("click", () => { if (uncertainCommand) issueCommand(null, null, uncertainCommand); });
$("refresh").addEventListener("click", async () => {
  if (busy) return;
  markBusy(true);
  try { await loadState(); announce("Workspace refreshed. Current requests and availability are shown."); }
  catch { announce("The workspace could not load. Check that the server is running, then select Refresh.", true); }
  finally { markBusy(false); }
});
markBusy(true);
loadState().catch(() => {
  $("inventory").replaceChildren(element("li", "empty-state", "Inventory could not load. Use Refresh to try again."));
  $("request-rows").replaceChildren();
  $("empty-queue").hidden = false;
  $("empty-queue").textContent = "Requests could not load. Use Refresh to try again.";
  announce("Cannot reach the local server. Check that it is running, then select Refresh.", true);
}).finally(() => markBusy(false));
