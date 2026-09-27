# CareCircle current voice demo script

This script matches the synthetic `demo-household` seed and the current browser, Supervisor, action policy, and voice builders. Run `PYTHONPATH=src .venv/bin/python scripts/reset_voice_demo.py --apply` and reload the browser before starting. Wait for each result and its progress trace before the next line. Say the quoted text exactly, or type it in the fallback field. The reset leaves Dad's morning dose unconfirmed, the walk unobserved, the simulated kitchen plug on, Maya unavailable, John on call, and cardiology at 14:30. The script uses one incident throughout.

## 1. Morning briefing

- **Say:** “CareCircle, how is Dad doing this morning?”
- **Route / public MCP:** deterministic `BRIEFING` → `get_household_briefing`.
- **Agents / private tools:** Supervisor briefing; Medication Agent (`get_medication_schedule`, `get_dose_history`, `find_missed_doses`, `get_medication_inventory`), Home Safety Agent (`run_home_safety_sweep`, Ring/entry, smoke/CO, plug reads), Care Coordinator Agent (`get_care_team`), and Logistics & Routine Agent (`get_upcoming_appointments`, `get_daily_routine`, `get_pharmacy_details`).
- **Speech:** Natural summary of unconfirmed medication and missing walk, normal smoke/CO, plug still on, Maya unavailable and John available, and cardiology at 2:30 PM. No safety questionnaire.
- **Care Summary / approval / persisted state:** Structured medication, home, plug, appointment, and open-task cards; no approval. This is read-only and creates no incident.
- **Verify:** `get_household_briefing` appears in the trace; no Triage or `create_incident` event.

## 2. New care concern

- **Say:** “Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.”
- **Route / public MCP:** `NEW_CONCERN` → `coordinate_care_request` without an incident ID.
- **Agents / private tools:** Supervisor and Triage Agent; `create_incident`, `get_emergency_plan`, `collect_safety_answers`, `evaluate_red_flag_rules`, `get_recent_anomalies`; Medication Agent `find_missed_doses`; Home Safety Agent `run_home_safety_sweep`; Care Coordinator Agent `find_on_call_contact`. The Triage model extracts signals, while the red-flag decision is deterministic.
- **Speech:** If required safety fields are missing, asks about Dad's responsiveness, chest pain, breathing, and speech. It does not announce a final risk level.
- **Care Summary / approval / persisted state:** The safety questions appear with the still-unresolved medication and plug state; no approval yet. One OPEN incident is saved with the reported confusion and `awaiting_safety_answers=true`.
- **Verify:** Record the incident ID from the current session; no caregiver alert is sent yet.

## 3. Safety answer, once

- **Say:** “He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.”
- **Route / public MCP:** active `AWAITING_SAFETY_ANSWERS` → `coordinate_care_request` with the **same** incident ID and session ID.
- **Agents / private tools:** Triage Agent `collect_safety_answers`; Safety Policy `evaluate_red_flag_rules`; Care Coordinator Agent `find_on_call_contact`, `prepare_caregiver_alert`, `update_care_task`.
- **Speech:** Explains that a caregiver check is needed, says it can alert a caregiver and schedule a follow-up, and ends with a clear approval question. It must not ask again whether Dad is awake.
- **Care Summary / approval / persisted state:** A single caregiver alert approval card appears. All four required safety facts, plus new confusion, are merged into this incident; `awaiting_safety_answers=false`; John is assigned and the morning task is `ASSIGNED`. The alert has not been sent.
- **Verify:** The approval card is for the current incident and the conversation is `AWAITING_SINGLE_APPROVAL`. If only part of the safety answer was captured, answer only the missing question shown before continuing.

## 4. Approve caregiver alert

- **Say:** “Yes.”
- **Route / public MCP:** active single approval → `confirm_action`, then one `get_incident_status` refresh.
- **Agents / private tools:** Safety Policy confirmation; Care Coordinator Agent `send_approved_alert` and `schedule_follow_up_check` through the approved workflow.
- **Speech:** States that the caregiver alert was sent and a follow-up was scheduled.
- **Care Summary / approval / persisted state:** Alert card becomes Completed and follow-up Scheduled. Pending caregiver approval clears. The same incident keeps John assigned, medication unresolved, plug on, and the saved safety answers.
- **Verify:** One alert and one follow-up, no new incident or repeated safety question.

## 5. Rest-of-day planning

- **Say:** “Also help with the rest of Dad's day.”
- **Route / public MCP:** explicit continuation → `coordinate_care_request` on the same incident, then `get_incident_status`.
- **Agents / private tools:** Medication Agent `get_medication_inventory`, `prepare_refill_request`; Logistics & Routine Agent `get_upcoming_appointments`, `get_daily_routine`, `get_pharmacy_details`, `prepare_ride_request`, `prepare_supply_request`.
- **Speech:** Mentions three prepared requests: medication refill, cardiology ride at 2:30 PM, and pill organizer; asks whether to approve all as drafts.
- **Care Summary / approval / persisted state:** One grouped three-action approval card. Refill, ride, and supply are `DRAFT`; nothing is purchased, booked, or sent to a pharmacy.
- **Verify:** Three distinct pending draft IDs and `AWAITING_MULTI_APPROVAL`.

## 6. Approve the drafts

- **Say:** “Approve all.”
- **Route / public MCP:** active multi-approval → three `confirm_action` calls, each followed by `get_incident_status`.
- **Agents / private tools:** Safety Policy `confirm_action` for each current ledger ID; no new specialist mutation.
- **Speech:** Confirms all three are approved drafts and nothing has been ordered or booked.
- **Care Summary / approval / persisted state:** Group approval card clears. Three drafts remain `DRAFT` with `APPROVED` approval state; medication and plug stay unchanged.
- **Verify:** No duplicate caregiver alert, booking, purchase, or incident.

## 7. Device proposal

- **Say:** “Turn off Dad's kitchen smart plug.”
- **Route / public MCP:** explicit device continuation → `coordinate_care_request` on the same incident, then `get_incident_status`.
- **Agents / private tools:** Home Safety Agent `get_stove_or_smart_plug_status`, `request_device_action`.
- **Speech:** Says the plug is on and asks approval to turn off the simulated plug.
- **Care Summary / approval / persisted state:** Plug remains on; one device approval card is pending.
- **Verify:** No plug state change before approval.

## 8. Approve device action

- **Say:** “Yes.”
- **Route / public MCP:** active single approval → `confirm_action`, then `get_incident_status`.
- **Agents / private tools:** Safety Policy confirmation and the approved simulated device action.
- **Speech:** “The kitchen plug is off.”
- **Care Summary / approval / persisted state:** Plug changes to off immediately; device action becomes Completed; earlier caregiver and draft state persists.
- **Verify:** One device execution and no safety questionnaire or new incident.

## 9. Caregiver resolution

- **Say:** “John checked on Dad. Dad is okay and confirmed he already took his morning medication.”
- **Route / public MCP:** explicit incident continuation → `coordinate_care_request`, then `get_incident_status`.
- **Agents / private tools:** Medication Agent `record_dose_status`; Care Coordinator Agent `update_care_task`.
- **Speech:** Says John's check and the reported morning dose were recorded, and the caregiver task is complete; no dosing advice.
- **Care Summary / approval / persisted state:** Medication `taken`, task `COMPLETED`, incident `RESOLVED`, plug off, John assigned, and three approved drafts still unsent. No approval is pending.
- **Verify:** The reported dose is recorded only once and the current incident ID remains unchanged.

## 10. Final persisted status

- **Say:** “What's the status of Dad's incident?”
- **Route / public MCP:** explicit incident status → `get_incident_status`.
- **Agents / private tools:** Read-only persisted status; no new private mutation.
- **Speech:** Concise natural summary: incident resolved, dose confirmed, caregiver check complete, plug off, drafts ready for review, and cardiology at 2:30 PM.
- **Care Summary / approval / persisted state:** Detailed structured status remains visible. No approval pending and no mutation.
- **Verify:** One incident; medication taken; task completed; plug off; caregiver John; two completed actions; three approved `DRAFT` requests; final counters 6/6 agents, 28/28 private tools, and 4/4 public MCP tools. Counters depend on progress telemetry arriving before the next turn.

The only external side effect in this synthetic run is the approved caregiver alert to the configured demo inbox, plus its one-shot follow-up schedule. Device control is simulated. The presenter should reset the synthetic voice demo after rehearsal; reset is a separate, explicit action and is not part of the ten spoken turns.

## Exact-script verification (2026-09-20)

After the scoped reset, all ten quoted phrases above were typed verbatim into the live localhost browser connected to the updated AgentCore Runtime. Each turn followed the listed route. The concern asked the safety questionnaire once; the complete answer cleared it and presented one caregiver approval. Both later “Yes.” turns confirmed their current pending actions rather than entering Triage. The browser finished at **6/6 agents, 28/28 private tools, and 4/4 public MCP tools**. Its final Care Summary showed incident `RESOLVED`, medication `taken`, caregiver task `COMPLETED`, kitchen plug `off`, John assigned, two completed actions, and three request drafts.

A read-only DynamoDB check found exactly one new `voice-*` incident from the run, ID `88321e0c-6ee2-473e-81c2-76c7cf7c7d16`, with `awaiting_safety_answers=false` and saved answers `{awake_and_responsive: true, chest_pain: false, severe_trouble_breathing: false, difficulty_speaking: false, new_or_worsening_confusion: true}`. Its ledger had one approved completed caregiver alert, one approved completed device change, and approved `DRAFT` refill, ride, and supply requests. The successful rehearsal incident was left in place; no post-run reset was performed.
