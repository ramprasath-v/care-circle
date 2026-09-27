# CareCircle full-build source-of-truth inventory

The implementation defines exactly six agent roles:

| Agent | Implementation | Local status |
| --- | --- | --- |
| CareCircle Supervisor | `src/carecircle/full_supervisor.py`, `src/carecircle/strands_orchestration.py` | COMPLETE |
| Triage Agent | `src/carecircle/agents/triage.py`, `src/carecircle/internal_tools.py` | COMPLETE |
| Medication Agent | `src/carecircle/agents/medication.py`, `src/carecircle/internal_tools.py` | COMPLETE |
| Home Safety Agent | `src/carecircle/full_supervisor.py`, `src/carecircle/internal_tools.py` | COMPLETE |
| Care Coordinator Agent | `src/carecircle/full_supervisor.py`, `src/carecircle/internal_tools.py` | COMPLETE |
| Logistics & Routine Agent | `src/carecircle/full_supervisor.py`, `src/carecircle/internal_tools.py` | COMPLETE |

The Strands supervisor uses five read-only specialist agents as tools for an
advisory plan. A local live call using Claude Sonnet 4.6 returned triage,
medication, and care coordinator for the hero concern. Deterministic Python code
always performs safety routing and approval decisions.

The exact 28 private tools are registered in `INTERNAL_TOOL_OWNERS` in
`src/carecircle/internal_tools.py`. Every tool returns a validated `ToolResult`.
The table below reports implementation and offline test coverage for every tool.
The live remote path additionally verified incident creation, safety evaluation,
medication lookup, home sweep, contact selection, alert preparation and publish,
follow-up scheduling, and status reads. The later seven-scene voice demo exercised all 28 private tools remotely through the same four public MCP tools; coverage was counted only from actual successful tool events.

| # | Tool | Owning agent | Implementation file | Provider | Test | Demo/use-case | Local status |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | `create_incident` | Triage | `internal_tools.py` | ActionLedger store | `test_triage_tools_persist_answers_and_find_anomalies` | Hero incident | COMPLETE |
| 2 | `get_emergency_plan` | Triage | `internal_tools.py` | CareProfiles store | same | Emergency short circuit | COMPLETE |
| 3 | `collect_safety_answers` | Triage | `internal_tools.py` | ActionLedger store | same | Multi-turn safety state | COMPLETE |
| 4 | `evaluate_red_flag_rules` | Triage | `internal_tools.py` | Deterministic policy | same | Hero/emergency | COMPLETE |
| 5 | `get_recent_anomalies` | Triage | `internal_tools.py` | CareEvents store | same | Triage context | COMPLETE |
| 6 | `get_medication_schedule` | Medication | `internal_tools.py` | CareProfiles store | `test_medication_tools_persist_facts_and_draft_only` | Daily briefing | COMPLETE |
| 7 | `get_dose_history` | Medication | `internal_tools.py` | CareEvents store | same | Daily briefing | COMPLETE |
| 8 | `find_missed_doses` | Medication | `internal_tools.py` | Deterministic schedule comparison | same | Hero incident | COMPLETE |
| 9 | `record_dose_status` | Medication | `internal_tools.py` | CareEvents store | same | Idempotent dose record | COMPLETE |
| 10 | `get_medication_inventory` | Medication | `internal_tools.py` | CareProfiles store | same | Inventory facts | COMPLETE |
| 11 | `prepare_refill_request` | Medication | `internal_tools.py` | ActionLedger draft | same | Refill draft | COMPLETE |
| 12 | `get_recent_ring_events` | Home Safety | `internal_tools.py` | SimulatedRingProvider | `test_home_tools_and_device_confirmation` | 07:42 door event | COMPLETE |
| 13 | `get_entry_activity_summary` | Home Safety | `internal_tools.py` | SimulatedRingProvider | same | Door event and missing expected walk | COMPLETE |
| 14 | `get_smoke_co_status` | Home Safety | `internal_tools.py` | SimulatedRingProvider | same | Normal smoke/CO | COMPLETE |
| 15 | `get_stove_or_smart_plug_status` | Home Safety | `internal_tools.py` | SimulatedRingProvider | same | Simulated plug ON until approval | COMPLETE |
| 16 | `run_home_safety_sweep` | Home Safety | `internal_tools.py` | SimulatedRingProvider | same | Hero/home briefing | COMPLETE |
| 17 | `request_device_action` | Home Safety | `internal_tools.py` | ActionLedger + simulated device | same | Approval-gated device action | COMPLETE |
| 18 | `get_care_team` | Care Coordinator | `internal_tools.py` | CareProfiles store | `test_coordinator_tools_sns_approval_and_follow_up` | Maya/John | COMPLETE |
| 19 | `find_on_call_contact` | Care Coordinator | `internal_tools.py` | CareProfiles escalation rule | same | John backup selection | COMPLETE |
| 20 | `prepare_caregiver_alert` | Care Coordinator | `internal_tools.py` | ActionLedger pending action | same | Hero alert card | COMPLETE |
| 21 | `send_approved_alert` | Care Coordinator | `internal_tools.py` | SNS adapter | same | Approved publish/idempotency | COMPLETE |
| 22 | `schedule_follow_up_check` | Care Coordinator | `internal_tools.py` | EventBridge Scheduler adapter | same | One-shot follow-up | COMPLETE |
| 23 | `update_care_task` | Care Coordinator | `internal_tools.py` | CareProfiles store | same | Care task state | COMPLETE |
| 24 | `get_upcoming_appointments` | Logistics & Routine | `internal_tools.py` | CareProfiles store | `test_rejection_never_sends_and_logistics_drafts` | 2:30 cardiology | COMPLETE |
| 25 | `get_daily_routine` | Logistics & Routine | `internal_tools.py` | CareProfiles store | same | Breakfast/med/walk | COMPLETE |
| 26 | `get_pharmacy_details` | Logistics & Routine | `internal_tools.py` | CareProfiles store | same | Synthetic pharmacy | COMPLETE |
| 27 | `prepare_ride_request` | Logistics & Routine | `internal_tools.py` | ActionLedger draft | same | Ride draft | COMPLETE |
| 28 | `prepare_supply_request` | Logistics & Routine | `internal_tools.py` | ActionLedger draft | same | Supply draft | COMPLETE |

| Public MCP tool | Implementation file | Provider/orchestrator | Test | Local status |
| --- | --- | --- | --- | --- |
| `coordinate_care_request` | `src/carecircle/app.py` | FullCareCircleSupervisor | `test_four_public_contracts_and_approval` | COMPLETE |
| `get_household_briefing` | `src/carecircle/app.py` | Parallel specialist fan-out | same | COMPLETE |
| `confirm_action` | `src/carecircle/app.py` | Deterministic ActionWorkflow | same | COMPLETE |
| `get_incident_status` | `src/carecircle/app.py` | Persisted ActionLedger/CareEvents | same | COMPLETE |

`CareCircleFullBuild` is deployed, and the existing Phase 3 AgentCore runtime was
updated in place. All four public MCP tools passed authenticated remote calls.
Live SNS publication, synthetic inbox delivery, EventBridge scheduling, Lambda
follow-up, and DynamoDB persistence were verified on 2026-09-20. No real caregiver
contact or physical Ring device is connected.
