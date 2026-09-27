"use strict";
const household_id = "demo-household",
  actor_role = "caregiver";
const $ = (selector) => document.querySelector(selector);
const AGENTS = [
  "CareCircle Supervisor",
  "Triage Agent",
  "Medication Agent",
  "Home Safety Agent",
  "Care Coordinator Agent",
  "Logistics & Routine Agent",
];
const TOOL_GROUPS = {
  "Triage Agent": [
    "create_incident",
    "get_emergency_plan",
    "collect_safety_answers",
    "evaluate_red_flag_rules",
    "get_recent_anomalies",
  ],
  "Medication Agent": [
    "get_medication_schedule",
    "get_dose_history",
    "find_missed_doses",
    "record_dose_status",
    "get_medication_inventory",
    "prepare_refill_request",
  ],
  "Home Safety Agent": [
    "get_recent_ring_events",
    "get_entry_activity_summary",
    "get_smoke_co_status",
    "get_stove_or_smart_plug_status",
    "run_home_safety_sweep",
    "request_device_action",
  ],
  "Care Coordinator Agent": [
    "get_care_team",
    "find_on_call_contact",
    "prepare_caregiver_alert",
    "send_approved_alert",
    "schedule_follow_up_check",
    "update_care_task",
  ],
  "Logistics & Routine Agent": [
    "get_upcoming_appointments",
    "get_daily_routine",
    "get_pharmacy_details",
    "prepare_ride_request",
    "prepare_supply_request",
  ],
};
const friendly = {
  briefing: "Checking today’s routine",
  strands_agents_as_tools_plan: "Supervisor planning",
  assess: "Checking safety",
  evaluate_red_flag_rules: "Checking safety rules",
  find_missed_doses: "Checking medication",
  run_home_safety_sweep: "Checking home activity",
  find_on_call_contact: "Finding caregiver",
  get_care_team: "Checking care team",
  get_upcoming_appointments: "Checking appointment",
  create_incident: "Saving incident",
  prepare_caregiver_alert: "Preparing caregiver alert",
  confirm_action: "Recording your decision",
  publish: "Sending caregiver alert",
  schedule_follow_up_check: "Scheduling follow-up",
  send_approved_alert: "Sending caregiver alert",
  request_device_action: "Preparing device approval",
  record_dose_status: "Recording reported medication status",
  prepare_refill_request: "Preparing refill draft",
  prepare_ride_request: "Preparing ride draft",
  prepare_supply_request: "Preparing supply draft",
  update_care_task: "Updating caregiver task",
  coordinate: "Coordinating care",
};
let incidentId = null,
  pending = [],
  busy = false,
  recording = false,
  transcribing = false,
  muted = false,
  audioUrl = null,
  activeAudio = null,
  playedText = "",
  recorder = null,
  mediaStream = null,
  audioContext = null,
  lastPromptedAction = null;
let followUpTimer = null,
  scheduledFollowUp = null;
const conversation = {
  household_id,
  session_id: null,
  incident_id: null,
  pending_actions: [],
  last_interaction_type: "IDLE",
  awaiting_approval: false,
  awaiting_safety_answers: false,
  safety_question: null,
  mode: "IDLE",
  next_appointment: null,
};
let batchApproving = false,
  reviewIndividually = false,
  confirmationSpeechPending = false;
function syncConversation(interaction) {
  conversation.incident_id = incidentId;
  conversation.pending_actions = pending.map(({ action }) => ({
    action_id: action.action_id,
    type: action.type,
  }));
  conversation.awaiting_approval = pending.length > 0;
  if (interaction) conversation.last_interaction_type = interaction;
  if (!batchApproving)
    conversation.mode =
      pending.length > 1
        ? "AWAITING_MULTI_APPROVAL"
        : pending.length
          ? "AWAITING_SINGLE_APPROVAL"
          : conversation.awaiting_safety_answers
            ? "AWAITING_SAFETY_ANSWERS"
            : incidentId
              ? "COMPLETE"
              : "IDLE";
}
const MUTATION_TOOLS = new Set([
  "send_approved_alert",
  "request_device_action",
  "schedule_follow_up_check",
  "update_care_task",
  "record_dose_status",
  "prepare_refill_request",
  "prepare_ride_request",
  "prepare_supply_request",
]);
const TERMINAL_ACTION_STATES = new Set([
  "COMPLETED",
  "APPROVED",
  "EXECUTED",
  "REJECTED",
  "CANCELLED",
]);
function isPendingApproval(action) {
  return (
    action.approval_required &&
    action.approval_state === "PENDING" &&
    !TERMINAL_ACTION_STATES.has(action.execution_state)
  );
}
const observedAgents = new Set(),
  observedTools = new Set(),
  observedPublic = new Set();
function status(text) {
  $("#state").textContent = text;
}
function error(text) {
  $("#error").textContent = text || "";
  if (text) status("Something went wrong");
}
function line(text, who) {
  const el = document.createElement("div");
  el.className = "line " + who;
  el.textContent = text;
  $("#conversation").append(el);
}
function counters() {
  $("#agent-count").textContent =
    `Agents exercised: ${observedAgents.size} / 6`;
  $("#tool-count").textContent = `Tools exercised: ${observedTools.size} / 28`;
  $("#mcp-count").textContent =
    `Public MCP tools exercised: ${observedPublic.size} / 4`;
}
function renderCoverage() {
  const root = $("#coverage");
  root.replaceChildren();
  for (const [owner, names] of Object.entries(TOOL_GROUPS)) {
    const group = document.createElement("div");
    const title = document.createElement("h3");
    title.textContent = `${owner} ${names.filter((name) => observedTools.has(name)).length}/${names.length}`;
    group.append(title);
    for (const name of names) {
      const row = document.createElement("div");
      row.className = "agent " + (observedTools.has(name) ? "done" : "");
      row.textContent = (observedTools.has(name) ? "✓ " : "○ ") + name;
      group.append(row);
    }
    root.append(group);
  }
}
function renderAgents() {
  const root = $("#agents");
  root.replaceChildren();
  for (const agent of AGENTS) {
    const el = document.createElement("div");
    el.className = "agent " + (observedAgents.has(agent) ? "done" : "");
    el.textContent =
      (observedAgents.has(agent) ? "✓ " : "○ ") + agent.replace(" Agent", "");
    root.append(el);
  }
}
function progress(e) {
  const state = String(e.status || "RUNNING").toUpperCase();
  const label =
    friendly[e.operation] ||
    e.operation?.replaceAll("_", " ") ||
    e.component ||
    "Working";
  $("#current-step").textContent =
    state === "FAILED"
      ? `${label} failed`
      : state === "NEEDS_APPROVAL"
        ? "Waiting for approval"
        : state === "COMPLETE"
          ? `${label} complete`
          : `${label}…`;
  if (AGENTS.includes(e.component)) {
    observedAgents.add(e.component);
    renderAgents();
  }
  if (e.kind === "tool" && state === "COMPLETE") observedTools.add(e.operation);
  counters();
  renderCoverage();
  const el = document.createElement("div");
  el.className = "step " + state;
  el.textContent = `${e.component || "CareCircle"} · ${e.operation || ""} · ${state}${e.latency_ms == null ? "" : ` · ${Math.round(e.latency_ms)} ms`}${e.provider ? " · " + e.provider : ""}`;
  $("#trace").prepend(el);
  if (
    [
      "create_incident",
      "confirm_action",
      "send_approved_alert",
      "schedule_follow_up_check",
      "request_device_action",
      "record_dose_status",
    ].includes(e.operation) &&
    state === "COMPLETE"
  ) {
    $("#action-progress").textContent = `✓ ${label}`;
  }
  if (
    e.kind === "tool" &&
    state === "COMPLETE" &&
    MUTATION_TOOLS.has(e.operation)
  ) {
    $("#action-progress").textContent =
      `✓ ${label} · refreshing persisted state`;
  }
}
async function jsonPost(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Request failed");
  return value;
}
async function speak(text) {
  if (muted || !text) return;
  status("Speaking…");
  try {
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text.slice(0, 1500) }),
    });
    if (!response.ok) throw new Error("SpeechUnavailable");
    const blob = await response.blob();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = URL.createObjectURL(blob);
    playedText = text;
    $("#replay").disabled = false;
    if (activeAudio) activeAudio.pause();
    const audio = new Audio(audioUrl);
    activeAudio = audio;
    await audio.play();
    audio.onended = () => status("Tap to speak");
  } catch (e) {
    if (e.name !== "AbortError")
      error(
        `CareCircle voice unavailable: ${e.message}. The text response remains visible.`,
      );
  }
}
// Speech uses typed MCP fields; the detailed screen summary is intentionally separate.
function spokenTime(time) {
  const match = typeof time === "string" && time.match(/^(\d{1,2}):(\d{2})$/);
  if (!match) return null;
  const hour = Number(match[1]);
  if (hour > 23) return null;
  return `${hour % 12 || 12}:${match[2]} ${hour < 12 ? "AM" : "PM"}`;
}
function spokenAppointment(appointment) {
  if (!appointment?.name) return null;
  const name = appointment.name.toLowerCase().replace(/\s+appointment$/i, "");
  const time = spokenTime(appointment.time);
  return `His ${name} appointment is ${time ? "at " + time : "coming up"}.`;
}
function voiceBriefing(value) {
  const parts = [];
  const medicationUnconfirmed = Boolean(
    value.medication_status?.unresolved?.length,
  );
  const walkMissing = (value.routine_deviations || []).some(
    (item) => item.routine_id === "walk" && item.status === "not_observed",
  );
  if (medicationUnconfirmed && walkMissing)
    parts.push(
      "Dad's morning medication hasn't been confirmed yet, and his usual morning walk hasn't been observed.",
    );
  else if (medicationUnconfirmed)
    parts.push("Dad's morning medication hasn't been confirmed yet.");
  else if (walkMissing)
    parts.push("Dad's usual morning walk hasn't been observed yet.");
  else if (value.unresolved_incidents?.length)
    parts.push("Dad has an open care concern to check on.");
  else
    parts.push(
      value.unavailable_domains?.length
        ? "I've checked Dad's care day, but some details aren't available yet."
        : "Dad's care day looks on track.",
    );
  const smoke = value.home_status?.smoke_co?.status;
  const plug = value.home_status?.stove?.status?.smart_plug;
  if (smoke?.smoke === "normal" && smoke?.co === "normal" && plug === "on")
    parts.push(
      "There are no smoke or carbon-monoxide alerts, but the kitchen smart plug is still on.",
    );
  else {
    if (smoke?.smoke === "normal" && smoke?.co === "normal")
      parts.push("There are no smoke or carbon-monoxide alerts.");
    if (plug === "on") parts.push("The kitchen smart plug is still on.");
  }
  const team = value.care_team || [];
  const primary = team.find((person) => person.role === "primary caregiver");
  const backup = team.find(
    (person) => person.role === "backup caregiver" && person.on_call,
  );
  if (primary && !primary.on_call && backup)
    parts.push(
      `${primary.name} is unavailable today, and ${backup.name} is available as backup.`,
    );
  else if (backup && medicationUnconfirmed)
    parts.push(`${backup.name} is available for a caregiver check.`);
  const appointment = spokenAppointment(value.next_appointment);
  if (appointment) parts.push(appointment);
  if (medicationUnconfirmed)
    parts.push("A caregiver check can help confirm the medication.");
  return parts.slice(0, 5).join(" ");
}
function voiceCoordinate(value) {
  const actions = value.proposed_actions || [];
  if (actions.length) {
    const type = actions[0].type;
    if (type === "notify_primary_caregiver" || type === "caregiver_alert")
      return "Dad's care concern needs a caregiver check. I can alert a caregiver and schedule a follow-up. Would you like me to do that?";
    if (type === "device_change")
      return "Turning off Dad's kitchen smart plug requires confirmation. Should I proceed?";
    return "A care action needs your approval. Would you like me to proceed?";
  }
  if (value.evidence?.some((item) => item.source === "caregiver_report"))
    return "The caregiver check and Dad's reported morning dose have been recorded. The caregiver task is complete.";
  return value.summary || "I have an update on Dad’s care.";
}
function voiceConfirmation(result, action, approved) {
  const caregiver =
    action.type === "notify_primary_caregiver" ||
    action.type === "caregiver_alert";
  if (!approved)
    return caregiver
      ? "Okay, I didn't send the caregiver alert."
      : action.type === "device_change"
        ? "Okay, I didn't change the kitchen plug."
        : "Okay, I didn't take that action.";
  if (result.execution_state === "DRAFT" && action.type.endsWith("_draft"))
    return `The ${draftLabel(action.type)} is ready as an approved draft. Nothing has been ordered or booked.`;
  if (result.execution_state !== "COMPLETED")
    return "Your decision has been recorded.";
  if (caregiver)
    return `I've sent the caregiver alert.${result.next_check_at ? " A follow-up is scheduled." : ""}`;
  if (action.type === "device_change")
    return "Done. Dad's kitchen smart plug is now off.";
  return "The approved action is complete.";
}
function draftLabel(type) {
  return (
    {
      refill_draft: "medication refill request",
      ride_draft: "ride request",
      supply_draft: "pill-organizer request",
    }[type] || "request"
  );
}
function voiceApprovalGroup(entries, appointment) {
  const types = new Set(entries.map((entry) => entry.action.type));
  if (
    entries.length === 3 &&
    types.size === 3 &&
    ["refill_draft", "ride_draft", "supply_draft"].every((type) =>
      types.has(type),
    )
  ) {
    const time = spokenTime(appointment?.time);
    return `I've prepared three requests: a medication refill, a ride for Dad's ${appointment?.name?.toLowerCase().replace(/\s+appointment$/i, "") || "next"} appointment${time ? " at " + time : ""}, and a pill organizer. I can keep all three as approved drafts. Would you like me to approve all of them?`;
  }
  return `There are ${entries.length} actions awaiting approval. Would you like me to approve all of them?`;
}
function voiceApprovalGroupResult(entries, approved) {
  const drafts = entries.every((entry) => entry.action.type.endsWith("_draft"));
  if (drafts)
    return approved
      ? `I've prepared all ${entries.length}. The ${entries.map((entry) => draftLabel(entry.action.type)).join(", ")} are ready as approved drafts. Nothing has been ordered or booked.`
      : `Okay, I didn't approve the ${entries.length} request drafts. Nothing has been ordered or booked.`;
  return approved
    ? `I've completed the ${entries.length} approved actions.`
    : `Okay, I rejected the ${entries.length} actions.`;
}
function voiceStatus(value) {
  const parts = [];
  const resolved =
    value.resolution_state === "RESOLVED" || value.status === "RESOLVED";
  if (resolved) parts.push("Dad's incident is resolved.");
  else if (value.status === "FOLLOW_UP_DUE")
    parts.push("Dad's follow-up is due, and a caregiver check is needed.");
  else parts.push("Dad's incident is still open.");
  if (
    value.medication_status === "taken" &&
    value.care_task_status === "COMPLETED"
  )
    parts.push(
      "His morning medication has been confirmed as taken, and the caregiver check is complete.",
    );
  else {
    if (value.medication_status === "taken")
      parts.push("His morning medication has been confirmed as taken.");
    else if (value.medication_status === "unresolved")
      parts.push("His morning medication hasn't been confirmed yet.");
    if (value.care_task_status === "COMPLETED")
      parts.push("The caregiver check is complete.");
    else if (value.care_task_status === "ASSIGNED" && value.assigned_caregiver)
      parts.push("A caregiver is assigned to the check.");
  }
  if (value.home_smart_plug === "off") parts.push("The kitchen plug is off.");
  else if (value.home_smart_plug === "on")
    parts.push("The kitchen plug is still on.");
  if (!resolved && value.next_check_at && value.status !== "FOLLOW_UP_DUE")
    parts.push("A follow-up is scheduled.");
  if (value.draft_actions?.length)
    parts.push(
      `${value.draft_actions.length === 1 ? "A request draft is" : "Request drafts are"} ready for review.`,
    );
  const appointment = spokenAppointment(value.next_appointment);
  return [
    ...parts.slice(0, appointment ? 4 : 5),
    ...(appointment ? [appointment] : []),
  ].join(" ");
}
function summary(text, title = "CareCircle update", spokenText = null) {
  $("#summary-title").textContent = title;
  $("#summary").textContent = text;
  line(text, "assistant");
  if (spokenText) speak(spokenText);
}
function factCards(facts) {
  const root = $("#summary-grid");
  root.replaceChildren();
  for (const [key, value] of Object.entries(facts)) {
    const el = document.createElement("div");
    el.textContent = `${key}: ${value}`;
    root.append(el);
  }
}
function renderIncidentState(value) {
  if (value.incident_id !== incidentId) return;
  factCards({
    Medication: value.medication_status || "unrecorded",
    "Kitchen plug": value.home_smart_plug || "unknown",
    Caregiver: value.assigned_caregiver || "unassigned",
    "Caregiver task": value.care_task_status || "unknown",
    Appointment: value.next_appointment?.name || "None",
  });
  const root = $("#state-cards");
  root.replaceChildren();
  const card = (label, state) => {
    const el = document.createElement("div");
    el.className = "card";
    el.textContent = `${label} — ${state}`;
    root.append(el);
  };
  for (const action of value.completed_actions || [])
    card(action.description || action.type, "Completed");
  for (const action of value.draft_actions || [])
    card(
      action.type.replaceAll("_", " ").replace(" draft", " request"),
      "DRAFT",
    );
  if (value.status === "FOLLOW_UP_DUE")
    card("Follow-up", "Due — caregiver check needed");
  else if (value.next_check_at)
    card("Follow-up", `Scheduled for ${value.next_check_at}`);
  if (value.resolution_state === "RESOLVED") card("Incident", "Resolved");
  const approvals = (value.pending_actions || []).filter(isPendingApproval);
  pending = approvals.map((action) => ({
    action,
    incident_id: value.incident_id,
  }));
  conversation.next_appointment =
    value.next_appointment || conversation.next_appointment;
  renderActions();
  scheduleFollowUpRefresh(value);
}
function scheduleFollowUpRefresh(value) {
  const at =
    value.resolution_state === "RESOLVED" || value.status === "FOLLOW_UP_DUE"
      ? null
      : value.next_check_at || null;
  if (at === scheduledFollowUp) return;
  if (followUpTimer) clearTimeout(followUpTimer);
  scheduledFollowUp = at;
  followUpTimer = null;
  if (at) {
    const id = value.incident_id;
    const delay = Math.max(0, new Date(at).getTime() - Date.now() + 10000);
    const readDue = async (attempt) => {
      followUpTimer = null;
      if (incidentId !== id) return;
      try {
        const latest = await refreshIncident(id);
        if (latest.status === "FOLLOW_UP_DUE")
          summary(
            "The scheduled follow-up is due. A caregiver check is needed.",
            "Follow-up due",
            voiceStatus(latest),
          );
        else if (at === latest.next_check_at && attempt === 0)
          followUpTimer = setTimeout(() => readDue(1), 10000);
      } catch (e) {
        error(`Follow-up status refresh failed: ${e.message}`);
      }
    };
    followUpTimer = setTimeout(() => readDue(0), delay);
  }
}
async function refreshIncident(id) {
  const value = await job("get_incident_status", {
    household_id,
    incident_id: id,
  });
  renderIncidentState(value);
  return value;
}
function actionCards(value) {
  if (value.proposed_actions?.length) {
    pending = value.proposed_actions.map((action) => ({
      action,
      incident_id: value.incident_id,
    }));
    renderActions();
  }
}
function renderActions() {
  syncConversation();
  const root = $("#actions");
  root.replaceChildren();
  if (batchApproving) {
    const note = document.createElement("div");
    note.className = "card";
    note.textContent = "Updating the prepared actions…";
    root.append(note);
    status("Processing approvals…");
    return;
  }
  if (pending.length > 1 && !reviewIndividually) {
    const card = document.createElement("div");
    card.className = "card";
    const title = document.createElement("p");
    title.textContent = `${pending.length} prepared actions`;
    const list = document.createElement("ul");
    for (const entry of pending) {
      const item = document.createElement("li");
      item.textContent = entry.action.type.endsWith("_draft")
        ? draftLabel(entry.action.type)
        : entry.action.description;
      list.append(item);
    }
    const yes = document.createElement("button");
    yes.textContent = "Approve All";
    yes.onclick = () => confirmAll(true);
    const review = document.createElement("button");
    review.textContent = "Review Individually";
    review.className = "secondary";
    review.onclick = () => {
      reviewIndividually = true;
      renderActions();
    };
    const no = document.createElement("button");
    no.textContent = "Reject All";
    no.className = "reject";
    no.onclick = () => confirmAll(false);
    card.append(title, list, yes, review, no);
    root.append(card);
  } else
    for (const entry of pending) {
      const card = document.createElement("div");
      card.className = "card";
      const description = document.createElement("p");
      description.textContent = entry.action.description;
      const hint = document.createElement("p");
      hint.className = "muted";
      hint.textContent =
        "Say Yes or No when one action is pending, or use these buttons.";
      const yes = document.createElement("button");
      yes.textContent = "Approve";
      const no = document.createElement("button");
      no.textContent = "Reject";
      no.className = "reject";
      yes.onclick = () => confirm(entry, true);
      no.onclick = () => confirm(entry, false);
      card.append(description, hint, yes, no);
      root.append(card);
    }
  if (pending.length) {
    $("#action-progress").textContent = "! Approval required";
    status("Waiting for approval");
    const key = pending
      .map((entry) => entry.action.action_id)
      .sort()
      .join(",");
    if (lastPromptedAction !== key) {
      lastPromptedAction = key;
      if (!confirmationSpeechPending)
        speak(
          pending.length > 1
            ? voiceApprovalGroup(pending, conversation.next_appointment)
            : voiceCoordinate({ proposed_actions: [pending[0].action] }),
        );
    }
  } else {
    lastPromptedAction = null;
    reviewIndividually = false;
  }
}
async function confirm(entry, approved) {
  if (busy || batchApproving) return;
  let succeeded = false;
  try {
    const result = await job("confirm_action", {
      household_id,
      incident_id: entry.incident_id,
      action_id: entry.action.action_id,
      approved,
    });
    succeeded = true;
    const kind = entry.action.type;
    const caregiver =
      kind === "notify_primary_caregiver" || kind === "caregiver_alert";
    let text;
    if (!approved)
      text = caregiver
        ? "Caregiver alert rejected. No alert sent."
        : kind === "device_change"
          ? "Device action rejected. The simulated plug was not changed."
          : "Action rejected. No action executed.";
    else if (result.execution_state === "COMPLETED" && caregiver)
      text = `Caregiver alert sent.${result.next_check_at ? " Follow-up scheduled." : ""}`;
    else if (result.execution_state === "COMPLETED" && kind === "device_change")
      text = "Simulated kitchen plug turned off.";
    else
      text = `${entry.action.description} ${result.execution_state || "Decision recorded"}.`;
    confirmationSpeechPending = true;
    try {
      await refreshIncident(entry.incident_id);
    } finally {
      confirmationSpeechPending = false;
    }
    syncConversation("APPROVAL");
    summary(
      text,
      "Action updated",
      voiceConfirmation(result, entry.action, approved),
    );
  } catch (e) {
    error(
      `${succeeded ? "Action succeeded, but its status could not be refreshed" : "Approval failed"}: ${e.message}`,
    );
  }
}
async function confirmAll(approved) {
  if (busy || batchApproving || pending.length < 2) return;
  const selected = pending.map((entry) => ({
    action: { ...entry.action },
    incident_id: entry.incident_id,
  }));
  batchApproving = true;
  conversation.mode = "PROCESSING";
  let completed = 0;
  try {
    const latest = await refreshIncident(selected[0].incident_id);
    const current = new Set(
      (latest.pending_actions || [])
        .filter(isPendingApproval)
        .map((action) => action.action_id),
    );
    if (selected.some((entry) => !current.has(entry.action.action_id)))
      throw new Error(
        "Pending actions changed. Please review the current list.",
      );
    for (const entry of selected) {
      await job("confirm_action", {
        household_id,
        incident_id: entry.incident_id,
        action_id: entry.action.action_id,
        approved,
      });
      completed++;
      await refreshIncident(entry.incident_id);
    }
    conversation.awaiting_safety_answers = false;
    conversation.safety_question = null;
    const text = approved
      ? `${selected.length} actions approved according to their policies.`
      : `${selected.length} actions rejected.`;
    summary(
      text,
      "Actions updated",
      voiceApprovalGroupResult(selected, approved),
    );
    syncConversation("GROUP_APPROVAL");
  } catch (e) {
    error(`${completed} of ${selected.length} actions recorded. ${e.message}`);
  } finally {
    batchApproving = false;
    syncConversation("GROUP_APPROVAL");
    renderActions();
  }
}
async function job(operation, args) {
  if (busy) throw new Error("CareCircle is already working");
  busy = true;
  $("#working-label-text").textContent = "CareCircle is working";
  $("#working-spinner").hidden = false;
  $("#send").disabled = true;
  $("#mic").disabled = true;
  status("Processing…");
  error("");
  try {
    const started = await jsonPost("/api/jobs", {
      operation,
      arguments: conversation.session_id
        ? { ...args, session_id: conversation.session_id }
        : args,
    });
    if (started.session_id) conversation.session_id = started.session_id;
    return await new Promise((resolve, reject) => {
      const events = new EventSource(`/api/jobs/${started.job_id}/events`);
      let settled = false;
      let resultReceived = false;
      let resultValue;
      events.onmessage = (message) => {
        const item = JSON.parse(message.data);
        if (item.type === "progress") progress(item);
        if (item.type === "result") {
          resultReceived = true;
          resultValue = item.value;
          observedPublic.add(operation);
          counters();
        }
        if (item.type === "error") {
          settled = true;
          events.close();
          reject(new Error(item.error));
        }
        if (item.type === "done") {
          events.close();
          if (!settled) {
            settled = true;
            if (!resultReceived)
              reject(new Error("Request completed without a result"));
            else {
              $("#current-step").textContent = "Care coordination complete";
              resolve(resultValue);
            }
          }
        }
      };
      events.onerror = () => {
        events.close();
        if (!settled) reject(new Error("Live connection lost"));
      };
    });
  } finally {
    busy = false;
    $("#working-label-text").textContent = "CareCircle is ready";
    $("#working-spinner").hidden = true;
    $("#send").disabled = false;
    $("#mic").disabled = transcribing;
    if (!pending.length) status("Tap to speak");
  }
}
function classifyCareIntent(text) {
  const phrase = text
    .toLowerCase()
    .replaceAll("’", "'")
    .replace(/^carecircle[,\s]+/, "")
    .trim();
  const safetyAnswer =
    /\b(?:awake and responsive|not awake|unresponsive|no chest pain|chest pain|breathing trouble|difficulty breathing|trouble breathing|difficulty speaking|trouble speaking)\b/.test(
      phrase,
    );
  if (conversation.awaiting_safety_answers && incidentId && safetyAnswer)
    return "SAFETY_ANSWER";
  const newConcern =
    /\b(?:confused|confusion|chest pain|fell|fallen|falling|had a fall|trouble breathing|difficulty breathing|breathing trouble|short of breath|unresponsive|not awake|something seems wrong|hasn't checked in|has not checked in|may have missed|might have missed|missed (?:his |the |morning )?medication)\b/.test(
      phrase,
    );
  const household = /\b(?:dad|father|him|household|family)\b/.test(phrase);
  const briefing =
    household &&
    /\b(?:how is|how's)\b.*\b(?:dad|father|him)\b|\b(?:update on|briefing|doing today|doing this morning|what's going on with|what is going on with|status today)\b/.test(
      phrase,
    );
  if (briefing && !newConcern) return "BRIEFING";
  if (
    !newConcern &&
    /\bincident\b.*\bstatus\b|\bstatus\b.*\bincident\b|\b(?:what's|what is)\b.*\bstatus\b/.test(
      phrase,
    )
  )
    return "INCIDENT_STATUS";
  if (
    /\b(?:turn (?:off|on)|smart plug|kitchen plug|rest of (?:his|dad's|the) day|ride request|refill request|supply request|already took)\b/.test(
      phrase,
    )
  )
    return "ACTION";
  if (newConcern) return "NEW_CONCERN";
  return "COORDINATE";
}
function logTurn(source, before, intent) {
  if (typeof console === "undefined" || !console.info) return;
  let hash = 2166136261;
  if (conversation.session_id)
    for (const char of conversation.session_id) {
      hash ^= char.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
  console.info(
    "carecircle_turn",
    JSON.stringify({
      session_hash: conversation.session_id
        ? (hash >>> 0).toString(16).padStart(8, "0")
        : null,
      source,
      state_before: before,
      selected_intent: intent,
      state_after: conversation.mode,
      incident_id: conversation.incident_id,
      pending_action_count: conversation.pending_actions.length,
    }),
  );
}
async function dispatch(text, source = "typed") {
  text = text.trim();
  if (!text || batchApproving || busy) return;
  const before = conversation.mode;
  let selectedIntent = "UNROUTED";
  line(text, "user");
  $("#live-transcript").textContent = text;
  error("");
  try {
    syncConversation("VOICE_TURN");
    const approvalPhrase = text.toLowerCase().trim().replace(/[.!?,]+$/, "").replace(/\s+/g, " ");
    if (
      pending.length > 1 &&
      pending.every(({ action }) => action.type.endsWith("_draft")) &&
      ["approve all", "approve them all", "approve all of them", "yes, approve all"].includes(approvalPhrase)
    ) {
      selectedIntent = "APPROVE_ALL";
      await confirmAll(true);
      return;
    }
    const intent = await jsonPost("/api/voice-intent", {
      transcript: text,
      pending_count: conversation.pending_actions.length,
    });
    if (intent.decision === "AMBIGUOUS") {
      selectedIntent = "AMBIGUOUS_APPROVAL";
      const message =
        "More than one action is pending. Please choose Approve All, Reject All, or Review Individually.";
      summary(message, "Choose an action", message);
      return;
    }
    if (intent.decision === "APPROVE_ALL" || intent.decision === "REJECT_ALL") {
      selectedIntent = intent.decision;
      await confirmAll(intent.decision === "APPROVE_ALL");
      return;
    }
    if (intent.decision === "APPROVE" || intent.decision === "REJECT") {
      selectedIntent = intent.decision;
      await confirm(pending[0], intent.decision === "APPROVE");
      return;
    }
    if (
      /^(?:yes|no|approve(?: (?:it|all|them all))?|reject(?: all)?|cancel(?: all)?|go ahead(?: with all)?|do it|don['’]t do (?:it|that)|yes to all|no to all)[.!?]?$/i.test(
        text,
      )
    ) {
      selectedIntent = "NO_APPROVAL_CONTEXT";
      const message = conversation.awaiting_approval
        ? "Please choose one of the pending actions."
        : "There are no actions waiting for approval.";
      summary(message, "Approval context", message);
      return;
    }
    const lower = text.toLowerCase();
    const route = classifyCareIntent(text);
    selectedIntent = route;
    let value;
    if (route === "BRIEFING") {
      value = await job("get_household_briefing", { household_id });
      conversation.next_appointment = value.next_appointment || null;
      syncConversation("BRIEFING");
      const medication = value.medication_status?.unresolved?.length
        ? "Unresolved"
        : "No exception recorded";
      const home = value.home_status?.entry?.summary || "Checked";
      const appointment = value.next_appointment;
      const plug = value.home_status?.stove?.status?.smart_plug || "unknown";
      const text = `Morning medication: ${medication}. Home: ${home}. Simulated kitchen plug: ${plug}. Next appointment: ${appointment?.name || "none"} at ${appointment?.time || "—"}. Open care tasks: ${(value.open_care_tasks || []).length}.`;
      factCards({
        Medication: medication,
        Home: home,
        "Kitchen plug": plug,
        Appointment: appointment?.name || "None",
      });
      summary(text, "Dad’s care day", voiceBriefing(value));
    } else if (route === "INCIDENT_STATUS" && incidentId) {
      value = await refreshIncident(incidentId);
      summary(
        `Incident ${value.status || value.resolution_state || "open"}. Caregiver: ${value.assigned_caregiver || "unassigned"}. Morning medication: ${value.medication_status || "unrecorded"}. Caregiver task: ${value.care_task_status || "unknown"}. Simulated kitchen plug: ${value.home_smart_plug || "unknown"}. Completed actions: ${(value.completed_actions || []).length}. Prepared drafts: ${(value.draft_actions || []).map((x) => x.type.replace("_draft", "")).join(", ") || "none"}. Follow-up: ${value.next_check_at || "closed or none"}. Next appointment: ${value.next_appointment?.name || "none"} at ${value.next_appointment?.time || "—"}.`,
        "Incident status",
        voiceStatus(value),
      );
    } else {
      const continuation =
        route === "ACTION" ||
        route === "SAFETY_ANSWER" ||
        /rest of.*day|appointment and medication supplies|already took.*medication/.test(
          lower,
        );
      if (
        conversation.mode === "AWAITING_SAFETY_ANSWERS" &&
        route !== "SAFETY_ANSWER" &&
        route !== "NEW_CONCERN"
      ) {
        const message =
          conversation.safety_question ||
          "Please answer the remaining safety question.";
        summary(message, "Safety check", message);
        return;
      }
      if (continuation && !incidentId)
        throw new Error(
          "Start a care incident first, then continue the same incident.",
        );
      const args = { household_id, actor_role, utterance: text };
      if (continuation || conversation.mode === "AWAITING_SAFETY_ANSWERS")
        args.incident_id = incidentId;
      value = await job("coordinate_care_request", args);
      incidentId = value.incident_id;
      conversation.awaiting_safety_answers =
        value.awaiting_safety_answers === true ||
        (value.awaiting_safety_answers == null &&
          /awake and responsive.*\?/i.test(value.summary));
      conversation.safety_question = conversation.awaiting_safety_answers
        ? value.summary
        : null;
      syncConversation("CARE_COORDINATION");
      const draftPreparation = value.summary.startsWith("Prepared drafts");
      const screenText = conversation.awaiting_safety_answers
        ? value.summary
        : `${value.summary} Risk: ${value.risk_level}.`;
      let refreshed = false;
      try {
        await refreshIncident(incidentId);
        refreshed = true;
      } catch (e) {
        error(
          `Care coordination succeeded, but its status could not be refreshed: ${e.message}`,
        );
      }
      if (!refreshed) actionCards(value);
      summary(
        screenText,
        draftPreparation ? "Prepared drafts" : "Care coordination",
        (value.proposed_actions || []).length || draftPreparation
          ? null
          : voiceCoordinate(value),
      );
    }
  } catch (e) {
    error(`Request failed: ${e.message}`);
  } finally {
    syncConversation();
    logTurn(source, before, selectedIntent);
  }
}
// Web Audio captures signed 16-bit little-endian mono PCM; no browser AWS credentials.
async function startRecording() {
  if (busy || transcribing) return;
  try {
    status("Waiting for microphone access…");
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    });
    audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(mediaStream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    let carry = [];
    let position = 0;
    const ratio = audioContext.sampleRate / 16000;
    processor.onaudioprocess = (e) => {
      if (!recording) return;
      const input = e.inputBuffer.getChannelData(0);
      carry.push(...input);
      const out = [];
      while (position + 1 < carry.length) {
        const index = Math.floor(position),
          fraction = position - index;
        out.push(carry[index] * (1 - fraction) + carry[index + 1] * fraction);
        position += ratio;
      }
      const consumed = Math.floor(position);
      carry = carry.slice(consumed);
      position -= consumed;
      const bytes = new ArrayBuffer(out.length * 2),
        view = new DataView(bytes);
      out.forEach((sample, i) =>
        view.setInt16(i * 2, Math.max(-1, Math.min(1, sample)) * 32767, true),
      );
      chunks.push(new Uint8Array(bytes));
      if (chunks.reduce((n, x) => n + x.length, 0) > 640000) stopRecording();
    };
    source.connect(processor);
    processor.connect(audioContext.destination);
    recorder = { chunks, processor, source };
    recording = true;
    $("#mic").classList.add("listening");
    $("#mic").setAttribute("aria-label", "Stop recording");
    status("Listening…");
    $("#live-transcript").textContent =
      "Speak naturally, then tap the microphone to stop.";
  } catch (e) {
    error(
      `Microphone unavailable: ${e.name || e.message}. You can type below.`,
    );
  }
}
async function stopRecording() {
  if (!recording || transcribing) return;
  recording = false;
  transcribing = true;
  $("#mic").disabled = true;
  $("#mic").classList.remove("listening");
  $("#mic").setAttribute("aria-label", "Tap to speak");
  try {
    recorder.processor.disconnect();
    recorder.source.disconnect();
    mediaStream.getTracks().forEach((track) => track.stop());
    await audioContext.close();
    const blob = new Blob(recorder.chunks, {
      type: "application/octet-stream",
    });
    status("Understanding request…");
    if (blob.size < 6400) {
      error("Recording was too short. Please try again.");
      return;
    }
    const response = await fetch("/api/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: blob,
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Transcription failed");
    await dispatch(result.transcript, "microphone");
  } catch (e) {
    error(`Could not understand the recording: ${e.message}`);
  } finally {
    transcribing = false;
    $("#mic").disabled = busy;
  }
}
$("#mic").onclick = () => (recording ? stopRecording() : startRecording());
$("#mute").onclick = () => {
  muted = !muted;
  $("#mute").textContent = muted ? "🔇 Voice off" : "🔊 Voice on";
  $("#mute").setAttribute("aria-pressed", String(muted));
  if (muted && activeAudio) activeAudio.pause();
};
$("#replay").onclick = () => {
  if (playedText) speak(playedText);
};
$("#prompt-form").onsubmit = (e) => {
  e.preventDefault();
  const input = $("#prompt"),
    text = input.value;
  input.value = "";
  return dispatch(text, "typed");
};
document
  .querySelectorAll("[data-prompt]")
  .forEach(
    (button) =>
      (button.onclick = () => dispatch(button.dataset.prompt, "typed")),
  );
renderAgents();
renderCoverage();
