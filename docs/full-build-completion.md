# CareCircle full-build verification — 2026-09-20

The approved full build is deployed in `us-east-1` under the non-root
`carecircle-admin` SSO session. `CareCircleFullBuild`, `CareCirclePhase3Prerequisites`,
and `AgentCore-CareCirclePhase3-default` are all `UPDATE_COMPLETE`. The existing
AgentCore runtime and `DEFAULT` endpoint were updated in place and are `READY`.
The temporary Phase 3 deployment policy remains version `v9`; the runtime role
kept the same physical role ID.

| Requirement | Status | Evidence |
| --- | --- | --- |
| Six named agents | COMPLETE | `AGENT_NAMES`; live Supervisor, Triage, Medication, Home Safety, and Care Coordinator trace; Logistics & Routine covered by offline tests and briefing |
| Exact 28 private tools | COMPLETE | `INTERNAL_TOOL_OWNERS`; 28-row matrix in `full-build-inventory.md`; all called in tests |
| Exact four public MCP tools | COMPLETE | IAM-authenticated briefing, coordinate, confirm, and status calls returned validated structures |
| Three DynamoDB tables | COMPLETE | CareProfiles, CareEvents, and ActionLedger seeded and used by the live flow |
| SNS caregiver alerts | COMPLETE | Published alert and persisted `caregiver_alert_delivered` event in synthetic inbox |
| EventBridge follow-ups | COMPLETE | One-shot schedule invoked `CareCircleFollowUp` and requested automatic deletion |
| Home/Ring abstraction and simulator | COMPLETE | `RingProvider`, `SimulatedRingProvider`, home tool tests |
| Deterministic action policy | COMPLETE | `policy_decision` and red-flag rule tests |
| Human approval flow | COMPLETE | Remote MCP approval published once; idempotent retry scheduled follow-up without duplicate SNS publish |
| Persistent incidents and ActionLedger | COMPLETE | Live incident, completed action, pending backup action, and event records verified |
| Background follow-up | COMPLETE | Lambda ran; incident changed to `FOLLOW_UP_DUE`, backup action remained pending approval |
| Household briefing | COMPLETE | Parallel `asyncio.gather` with partial-failure tests; remote MCP and live browser response |
| Alexa-style simulator | COMPLETE | `GET /` HTTP 200 and `/api/mcp` HTTP 200 against live remote briefing |
| Visible trace panel | COMPLETE | Metadata-only panel and live response trace; local web/API verified |
| AgentCore | COMPLETE | Existing runtime updated in place; runtime and endpoint `READY`; new ECR digest verified |
| Strands | COMPLETE | Live planning and triage spans succeeded in runtime logs |
| Claude Sonnet 4.6 | COMPLETE | `AWS/Bedrock` `Invocations` metric for `us.anthropic.claude-sonnet-4-6` in remote test minutes |
| Tests | COMPLETE | 52 passed |
| Full-build deployment | COMPLETE | `CareCircleFullBuild` and the two existing stacks `UPDATE_COMPLETE` |

The clean full remote script returned incident
`6b27648e-c022-4e59-9efe-478484d75247`, risk `high`, one completed alert,
caregiver `maya`, SNS message ID `ab739a5e-c236-5fe0-8e9c-f974f9bdb765`,
and a next check time. Briefing → request → approval → status took **53,436.41 ms**.
A later status call returned `FOLLOW_UP_DUE`, one completed action, one pending
backup escalation, and a persisted follow-up event.

The local browser rendered the live daily briefing: morning medication unresolved,
normal home activity, cardiology at 14:30, and one open task. Its trace panel
displayed an AgentCore/MCP `get_household_briefing` success with 2,948 ms elapsed,
plus Medication, Home Safety, Care Coordinator, and Logistics & Routine briefing
steps. The specialist briefing rows have no fabricated latency values because
the briefing API does not return per-specialist timings.

The updated ECR image digest is
`sha256:2691887befb919779e7bb37c3e8e1379c78fdde4ad16278c05aead0606cd971f`.
Runtime ARN:
`arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/CareCirclePhase3_CareCircleMcp-XjLaBWDGYa`.
The portable AgentCore config was restored to `000000000000` placeholders after
deployment.

CloudWatch logs for the live request show MCP, Strands planning, Triage,
deterministic safety policy, Medication, Home Safety, Care Coordinator, and
successful Supervisor completion. They include only identifiers, operation names,
outcomes, and latency, not the utterance, credentials, or medication records.
CloudWatch `AWS/Bedrock` recorded 4 invocations at 19:50Z and 10 at 19:51Z for
the configured Claude Sonnet 4.6 inference profile. These account-level counts
corroborate the model path but are not per-incident traces.

The first approval published SNS but `CreateSchedule` failed because the
Scheduler execution-role trust used a schedule ARN. AWS requires the schedule
**group** ARN in `aws:SourceArn`. Only that trust condition was changed to
`schedule-group/default`; an idempotent retry finished the first schedule
without sending a second alert. The later complete remote run passed. The alert
reaches a synthetic Lambda-backed demo inbox, not a real caregiver. No successful
infrastructure was cleaned up.

After both follow-ups executed, `list-schedules --name-prefix carecircle-`
returned `[]`, confirming their requested automatic deletion. The 52-test suite
and final CloudFormation template validation passed after the trust correction.

## Ongoing cost estimate

At near-idle hackathon use, the existing customer-managed ECR KMS key is about
**$1/month**; the two retained ECR image entries total about 207 MB, roughly
**$0.02/month** at $0.10/GB-month, before any applicable free tier. The three
on-demand DynamoDB tables, SNS topic, Scheduler, Lambda, AgentCore microVM runtime,
Bedrock Claude inference, CloudWatch logs, and asset S3 storage have usage-based
charges; there is no reliable fixed monthly total without request and token volume.
The demo's SNS/Lambda/Scheduler operations are small. Claude token use and
AgentCore session compute can dominate if the demo is run often. Build minutes
are charged when CodeBuild runs, not while idle. This estimate is not an AWS bill.
See [KMS](https://aws.amazon.com/kms/pricing/),
[ECR](https://aws.amazon.com/ecr/pricing/),
[AgentCore](https://aws.amazon.com/bedrock/agentcore/pricing/),
[DynamoDB](https://aws.amazon.com/dynamodb/pricing/),
[SNS](https://aws.amazon.com/sns/pricing/),
[Scheduler](https://aws.amazon.com/eventbridge/pricing/), and
[Lambda](https://aws.amazon.com/lambda/pricing/) pricing.
