# CareCircle full-build resource and IAM review

This review is for the **new** `CareCircleFullBuild` stack in `us-east-1`, account
`109837542034`, plus an in-place update of `CareCirclePhase3Prerequisites` and the
existing `AgentCore-CareCirclePhase3-default` runtime. The previous Phase 3
deployment and its temporary CDK execution policy remain in place.

## New CloudFormation resources

| Type | Physical name | Purpose |
| --- | --- | --- |
| DynamoDB table | `CareCircleCareProfiles` | Synthetic household profile, contacts, medications, routine, appointment, pharmacy, devices |
| DynamoDB table | `CareCircleCareEvents` | Dose status, home events, SNS delivery, follow-up events |
| DynamoDB table | `CareCircleActionLedger` | `INCIDENT` record plus one row per approval action |
| SNS topic | `CareCircleCaregiverAlerts` | Approved synthetic caregiver alerts |
| Lambda function | `CareCircleFollowUp` | One-shot scheduled follow-up and SNS demo-inbox delivery |
| CloudWatch log group | `/aws/lambda/CareCircleFollowUp` | 30-day retained execution metadata |
| IAM role | `CareCircleFollowUpLambdaRole` | Lambda access to the two state tables and its own logs |
| IAM role | `CareCircleFollowUpSchedulerRole` | Scheduler permission to invoke only the follow-up Lambda |
| Lambda permission | generated under `CareCircleFullBuild` | Allows only this SNS topic to invoke the function |
| SNS subscription | generated under `CareCircleFullBuild` | Routes topic messages to the synthetic Maya inbox represented by a CareEvents delivery record |

EventBridge Scheduler schedules are created only after a caller approves a
caregiver alert. Each schedule has name `carecircle-<incident-uuid>`, invokes the
existing `CareCircleFollowUp` Lambda once, and requests automatic deletion.
No endpoint for a real caregiver is configured. SNS publication and delivery to the
synthetic inbox can be verified, but this does not establish delivery to a person.

## Existing runtime-role change

The `CareCirclePhase3AgentCoreRuntimeRole` keeps its Claude Sonnet 4.6, ECR, logging,
and telemetry permissions. The local prerequisite template adds only:

- DynamoDB read/write/query on the three named CareCircle tables, plus Scan on
  `CareCircleActionLedger` for the demo household incident list.
- `sns:Publish` on `CareCircleCaregiverAlerts`.
- `scheduler:CreateSchedule` and `scheduler:GetSchedule` on
  `schedule/default/carecircle-*`.
- `iam:PassRole` on `CareCircleFollowUpSchedulerRole` only when passed to
  `scheduler.amazonaws.com`.

The temporary CDK deployment policy remains unchanged. No additional Bedrock model
permission or unrelated application service is requested.

## Verification already done

- Non-root `carecircle-admin` SSO identity reconfirmed.
- Both CloudFormation templates passed AWS `validate-template`.
- AgentCore project passed `agentcore validate --json`.
- 52 offline tests pass, including all 28 internal tools, four MCP contracts,
  approval/idempotency, the inline Lambda, and the local web proxy.
- Cached ARM64 Phase 3 image was overlaid with current source for a local test.
  MCP initialization, four-tool listing, and household briefing succeeded over
  `127.0.0.1:8766/mcp`.
- Updated dependency lock passed `uv lock --check --offline` in that ARM64 image.

The production Dockerfile build could not reach Docker Hub or GHCR for base-image
metadata from this host. The local cached-image overlay verifies application startup
but does not replace the pending CodeBuild image build.

## Executed deployment sequence — 2026-09-20

1. Deploy `infra/full-build.yaml` as `CareCircleFullBuild` with
   `CAPABILITY_NAMED_IAM` and CareCircle tags.
2. Run `scripts/seed_demo.py` against the three named tables.
3. Apply the reviewed `CareCirclePhase3Prerequisites` runtime-role policy update
   in place. Preserve the temporary CDK policy document.
4. Substitute account `109837542034` only in the local AgentCore deployment copy
   of `agentcore.json`; deploy the existing AgentCore project in place; restore
   the checked-in `000000000000` placeholders afterward.
5. Verify runtime and endpoint `READY`, ECR digest, and all four remote MCP tools.
6. Run `scripts/test_full_remote.py`; verify SNS publish and Lambda delivery event,
   ActionLedger rows, EventBridge schedule, and subsequent one-shot follow-up.
7. Run the local web client against the real AgentCore runtime and inspect its
   trace panel; inspect privacy-safe logs.

The user subsequently gave direct approval for this exact resource set. Steps 1–7
were completed under the non-root `carecircle-admin` SSO role. The new stack is
`UPDATE_COMPLETE`; both existing stacks are `UPDATE_COMPLETE`. Runtime and
endpoint are `READY` under the original runtime ARN. The deployment policy stayed
at version `v9`, and the runtime role kept its original physical ID.

The exact new stack resources are the three named DynamoDB tables, SNS topic,
`CareCircleFollowUp` Lambda, its log group, `CareCircleFollowUpLambdaRole`,
`CareCircleFollowUpSchedulerRole`, the SNS subscription, and the Lambda invoke
permission. The two one-shot `carecircle-<incident-id>` schedules were created
by approved demo actions, outside CloudFormation, with automatic deletion
requested. No unrelated resource was modified.

The first approval reached SNS but Scheduler rejected the execution role trust:
`The execution role you provide must allow AWS EventBridge Scheduler to assume
the role.` The template had used
`arn:${AWS::Partition}:scheduler:${AWS::Region}:${AWS::AccountId}:schedule/default/carecircle-*`
as `aws:SourceArn`. [AWS Scheduler documentation](https://docs.aws.amazon.com/scheduler/latest/UserGuide/cross-service-confused-deputy-prevention.html)
requires the **schedule group** ARN. The sole correction was an in-place role
trust update to
`arn:${AWS::Partition}:scheduler:${AWS::Region}:${AWS::AccountId}:schedule-group/default`,
with `aws:SourceAccount` unchanged. No runtime or deployment permissions were
broadened. Reconfirming the same action scheduled follow-up without publishing
another alert; a separate full remote run then passed in 53,436.41 ms.

SNS delivered only to the Lambda-backed synthetic inbox. A scheduled follow-up
ran and persisted `FOLLOW_UP_DUE` plus a new backup-caregiver action in `PENDING`
state. The web client served HTTP 200 and proxied a live remote briefing through
its server-side AWS client. Full evidence is in `docs/full-build-completion.md`.
