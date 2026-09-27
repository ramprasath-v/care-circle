# CareCircle

CareCircle is a synthetic care-coordination hackathon demo for families helping an older adult live independently. It combines an IAM-authenticated MCP service on Amazon Bedrock AgentCore with persistent incident state, approval-gated caregiver alerts, a one-shot follow-up, and a local Alexa-style browser client. It does not diagnose, prescribe, call emergency services, operate real Ring devices, or contact a real caregiver.

The full build was deployed and verified in `us-east-1` on 2026-09-20. The existing AgentCore runtime was updated in place; it and its `DEFAULT` endpoint are `READY`. The verified resource and integration report is [docs/full-build-completion.md](docs/full-build-completion.md), with the exact [28 private tools and four public MCP tools](docs/full-build-inventory.md).

## Live architecture

```text
Chrome browser over App Runner HTTPS
  → Python/Starlette server with App Runner instance-role credentials
  → server-side IAM-authenticated MCP client
  → AgentCore Runtime /mcp
  → CareCircle Supervisor (Strands, Claude Sonnet 4.6)
  → Triage → deterministic red-flag policy
  → Medication / Home Safety / Care Coordinator / Logistics & Routine
  → DynamoDB incident + ActionLedger
  → human approval → SNS → synthetic caregiver inbox
                   → EventBridge Scheduler → follow-up Lambda → DynamoDB
```

The six named agent roles are the Supervisor and five specialists. Exactly 28 private typed tools are owned by those specialists. The public MCP surface contains only `coordinate_care_request`, `get_household_briefing`, `confirm_action`, and `get_incident_status`. Strands agents-as-tools produce an advisory plan; deterministic Python controls red flags, state mutation, and approval. No prompt can authorize an external action by itself.

## Public HTTPS demo

The current browser client is deployed at **https://9umkurqacc.us-east-1.awsapprunner.com**. AWS App Runner serves the existing Python/Starlette application from the private `carecircle/web` ECR repository and supplies the TLS certificate and public HTTPS endpoint. The browser calls only the Python server; it receives no AWS credentials. The App Runner instance role invokes the existing AgentCore runtime and `DEFAULT` endpoint, streams recorded audio to Amazon Transcribe, synthesizes speech with Amazon Polly, and reads privacy-safe progress events from the existing AgentCore CloudWatch log group. The deployment creates no VPC, NAT gateway, load balancer, certificate, domain, data store, or AgentCore runtime.

To publish a new frozen web image, choose a new immutable tag and update the same stack:

```bash
export AWS_PROFILE=carecircle-admin
export AWS_REGION=us-east-1
export WEB_TAG=YYYYMMDD-N
aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin 109837542034.dkr.ecr.us-east-1.amazonaws.com
docker build --platform linux/amd64 -f Dockerfile.web -t "109837542034.dkr.ecr.us-east-1.amazonaws.com/carecircle/web:$WEB_TAG" .
docker push "109837542034.dkr.ecr.us-east-1.amazonaws.com/carecircle/web:$WEB_TAG"
aws cloudformation deploy --region "$AWS_REGION" --stack-name CareCircleWebHosting \
  --template-file infra/web-hosting.yaml --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "ImageIdentifier=109837542034.dkr.ecr.us-east-1.amazonaws.com/carecircle/web:$WEB_TAG"
```

App Runner writes service and application logs without adding application log permissions:

```bash
aws logs tail /aws/apprunner/carecircle-web/9d2bdc8e94a444be82e47c6758ba4f98/application --region us-east-1 --follow
aws logs tail /aws/apprunner/carecircle-web/9d2bdc8e94a444be82e47c6758ba4f98/service --region us-east-1 --follow
```

To stop compute charges while retaining the web resources, pause only this service. To remove only the web-hosting resources, delete its ECR images first and then its CloudFormation stack:

```bash
aws apprunner pause-service --region us-east-1 --service-arn arn:aws:apprunner:us-east-1:109837542034:service/carecircle-web/9d2bdc8e94a444be82e47c6758ba4f98
aws ecr batch-delete-image --region us-east-1 --repository-name carecircle/web --image-ids imageTag=20260927-1
aws cloudformation delete-stack --region us-east-1 --stack-name CareCircleWebHosting
aws cloudformation wait stack-delete-complete --region us-east-1 --stack-name CareCircleWebHosting
```

The three tables are `CareCircleCareProfiles`, `CareCircleCareEvents`, and `CareCircleActionLedger`. All seeded people, medication records, routine events, and contact details are synthetic. The SNS subscriber writes a demo-inbox event through `CareCircleFollowUp`; it does not deliver to a person. Follow-up schedules are one-shot and request automatic deletion. A missed follow-up creates a backup-caregiver action that still requires approval.

## Run and verify

Requirements: Python 3.11+, the locked dependencies, and AWS credentials for the non-root `carecircle-admin` profile. Set `AWS_REGION=us-east-1` and `BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6`. No AWS credentials are stored in the repository or sent to the browser.

```bash
cd /Users/ramprasath/Documents/ChatGPT/CareCircle
PYTHONPATH=src .venv/bin/python -m pytest -q
export AWS_PROFILE=carecircle-admin
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6
export AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/CareCirclePhase3_CareCircleMcp-XjLaBWDGYa
PYTHONPATH=src .venv/bin/python scripts/test_full_remote.py
```

The remote test calls all four MCP tools, validates their Pydantic responses, approves a synthetic caregiver alert, checks persisted status, and prints total latency. It creates a new synthetic incident, sends one SNS message to the demo inbox, and schedules one follow-up. The 2026-09-20 run passed in 53.4 seconds. CloudWatch recorded Claude Sonnet 4.6 invocations in the same test window and privacy-safe orchestration logs for Supervisor, Triage, policy, Medication, Home Safety, and Care Coordinator. A later status call confirmed `FOLLOW_UP_DUE` and a pending backup action.

To run the voice-first local browser client against the deployed runtime:

```bash
PYTHONPATH=src .venv/bin/python -m pip install -r requirements-voice.txt
PYTHONPATH=src .venv/bin/python -m carecircle.web
# Visit http://127.0.0.1:8765
```

The web server binds to localhost and signs MCP requests server-side. If port 8765 is occupied, set `CARECIRCLE_WEB_PORT=8766` and visit that port. Restart the local web server and reload the page after code updates so both voice-intent routing and browser state use the new version. Tap the microphone, grant microphone access to localhost, speak for 1–20 seconds, then tap again. The browser converts mono microphone samples to 16 kHz PCM; the server streams that clip to Amazon Transcribe. CareCircle routes the transcript through the same four MCP tools, reads session-correlated metadata-only progress from the existing AgentCore CloudWatch log group, and sends a separate natural summary of the structured result through Amazon Polly (Ruth neural voice). Voice on/off and replay controls sit beneath the microphone. Typed prompts remain available. The browser retains the current incident, safety-question state, and pending action IDs between turns. A single action accepts Yes/Approve/Go ahead or No/Reject/Cancel; multiple pending actions accept Approve All or Reject All, with a Review Individually option. The browser receives no AWS credentials. This remains a local demo client, not a public hosted site.

Run the live speech loop without microphone hardware, then verify real remote progress:

```bash
PYTHONPATH=src .venv/bin/python scripts/test_voice_live.py
PYTHONPATH=src .venv/bin/python scripts/test_live_progress.py
```

The speech check synthesizes a test phrase as 16 kHz PCM through Polly, transcribes it with Amazon Transcribe, and synthesizes the final CareCircle voice MP3. The progress check creates a synthetic incident and validates a live CareResponse; it does not approve a proposed action. Voice and progress use the local `carecircle-admin` SSO session, so there are no new persistent AWS resources or runtime-role permissions. Runtime progress instrumentation was updated in place in the existing AgentCore container; the role and four-tool MCP surface were unchanged.

The source-of-truth infrastructure is [infra/full-build.yaml](infra/full-build.yaml) and [infra/iam/phase3-prerequisites.yaml](infra/iam/phase3-prerequisites.yaml). The reviewed AWS resource set and the Scheduler trust correction are in [infra/full-build-review.md](infra/full-build-review.md). AgentCore config is in [infra/agentcore/CareCirclePhase3/agentcore/agentcore.json](infra/agentcore/CareCirclePhase3/agentcore/agentcore.json); its `000000000000` values are portable placeholders, not deployed account values. The temporary Phase 3 deployment policy remains version `v9` and was not tightened during the full-build update. [docs/friction-log.md](docs/friction-log.md) records deployment issues and fixes.

## Safety and scope

CareCircle uses a deterministic emergency red-flag short circuit and never makes a diagnosis or dosing decision. Medication status is a recorded fact, not advice. Alerts, simulated device changes, purchases, and bookings pass through an explicit action policy. Refill, ride, and supply requests remain drafts. Runtime logs omit utterances, prompts, medication content, and credentials. Real identity, consent, caregiver delivery, and device integrations would require separate product and security work.

## Current voice demo

Use the existing `carecircle-admin` SSO profile and runtime ARN shown above. No new stack, role, public MCP tool, or private tool was added. This flow deliberately creates one synthetic incident, one caregiver alert to the demo inbox, one one-shot follow-up schedule, one simulated device change, three unsent drafts, and a recorded caregiver resolution. The local reset deletes only `voice-*` and legacy `web-*` incident records for `demo-household` and their recorded one-shot schedules; it leaves other households, historical non-demo incidents, and all infrastructure untouched. It restores plug ON and a fresh unresolved dose event. The morning-check task is unassigned and does not appear as an active task; the pill-organizer request remains an unsent draft, not a seeded active task. Historical events are excluded from the new demo generation's briefing and incident status.

```bash
# Preview the exact synthetic voice incidents that would be reset:
PYTHONPATH=src .venv/bin/python scripts/reset_voice_demo.py
# Reset before a judge demo; --apply is required, and the command verifies plug ON:
PYTHONPATH=src .venv/bin/python scripts/reset_voice_demo.py --apply
# Reload the page to clear browser conversation context and observed counters.
# Start the local UI (use CARECIRCLE_WEB_PORT=8766 if 8765 is occupied):
PYTHONPATH=src .venv/bin/python -m carecircle.web
```

Use the exact ten-turn transcript in [docs/current-demo-script.md](docs/current-demo-script.md). It is derived from the current seed and code, includes the complete safety-answer turn, and was verified verbatim through typed browser input. Wait for each result and late progress events before continuing. The scripted concern lets CareCircle discover Maya's unavailability and John's backup role from the saved household profile.

The expandable **Full tool coverage** panel turns an existing private tool green only after a successful real runtime progress event. The panel reached 28/28 in the automated live run. A full hardware-free integration rehearsal uses the same four public MCP endpoints and SSE bridge:

After a successful incident mutation, the browser makes one read through the existing `get_incident_status` MCP tool and refreshes the medication, plug, caregiver task, completed action, follow-up, and draft cards from persisted state. A scheduled follow-up gets a due-time read and at most one retry for service delivery lag; the browser does not continuously poll or repeat the mutating action. The progress trace remains notification, not the source of business state.

```bash
PYTHONPATH=src .venv/bin/python scripts/reset_voice_demo.py --apply
PYTHONPATH=src .venv/bin/python scripts/test_full_voice_demo.py
PYTHONPATH=src .venv/bin/python scripts/reset_voice_demo.py --apply
```

The final live run on 2026-09-20 observed 6/6 agents, 28/28 private tools, 4/4 public MCP tools, one SNS message ID across original and repeated approval, a scheduled follow-up, plug OFF after approval, three DRAFT actions, a persisted taken report, and Polly audio. It took about 203 seconds including CloudWatch delivery waits. The final reset restored Robert/John, the unresolved dose, plug ON, and an OPEN caregiver task with no active `voice-*` incident. Physical microphone permission and recording remain a manual browser check; Polly-generated PCM was used to test the live Transcribe-to-AgentCore-to-Polly path without microphone hardware.

Keep `AGENT_RUNTIME_ARN` exported when running the reset: it verifies the saved plug record, an independent simulated-provider read, the home sweep, and the remote `get_household_briefing` all report ON, plus an unresolved dose and no active assigned task. Open a fresh browser page after resetting so its in-memory incident and cards are new. Typed turns and completed microphone transcriptions enter the same browser handler; the microphone stays disabled while transcription and that turn are in flight. Browser console `carecircle_turn` entries record only a short session hash, input source, interaction states, intent, incident ID, and pending-action count—never the utterance.

The first briefing uses parallel Medication, Home Safety, Care Coordinator, and Logistics & Routine specialist reads. It does not use Triage or create an incident. The local SSE bridge waits briefly for their actual CloudWatch tool-completion events before delivering the briefing result, so the first-turn agent and private-tool counters reflect observed execution. The exact first-turn check on 2026-09-20 produced 5/6 agents, 13/28 private tools, and 1/4 public MCP tools.

The state-isolation verification reran the remote flow with intermediate status reads and passed in about 297 seconds. It confirmed medication unresolved and plug ON after the caregiver alert, plug ON after the device request, plug OFF only after device approval, and medication taken only after the explicit caregiver report. A separate browser run displayed those transitions in the Care Summary immediately. The demo was reset afterward and the page reloaded to its ready state.

The conversation-state regression run also verified the revised order: after John’s alert, “Also help with the rest of Dad’s day” presents a grouped three-draft card; “Approve all” confirms the three current ledger IDs and leaves each request in the approved `DRAFT` state. It does not create another incident, send another caregiver alert, book a ride, order medication, or change the plug or dose. The updated live run observed 6/6 agents and 28/28 private tools, followed by a typed browser pass through the same sequence. Both synthetic verification incidents were reset; the final reset verified plug ON and no active voice incident.

The final remote briefing also excludes older unrelated incidents from the fresh demo generation while retaining those historical records. It returned medication unresolved, plug ON, Maya unavailable, John available, the 14:30 appointment, and no current demo incident after reset.
