# CareCircle AgentCore friction log

Only issues observed while preparing or deploying CareCircle are recorded here.

## AWS CLI session had expired

### Issue

Verify the active AWS identity before making a live Bedrock call.

### Expected

The configured `default` profile would return the caller identity.

### Actual

The AWS CLI reported that the session had expired and required `aws login`.

### Severity

Medium

### Workaround

Run `aws login --profile default`, then verify with
`aws sts get-caller-identity --profile default`.

### Suggested improvement

AgentCore setup documentation should put a credential-expiration check immediately
before the first live Bedrock or deployment command.

## Docker daemon was initially unavailable

### Issue

Inspect the local container runtime before building the AgentCore image.

### Expected

`docker version` would report both client and server versions.

### Actual

The Docker client was installed, but the Docker Desktop socket did not exist because
the daemon was not running.

### Severity

Low

### Workaround

Start Docker Desktop and rerun `docker version`.

### Suggested improvement

Local AgentCore container instructions should distinguish an installed Docker CLI
from a running Docker daemon.

## Required runtime values were not configured

### Issue

Run the live Bedrock integration check with the same environment configuration as
the application.

### Expected

`AWS_REGION` and `BEDROCK_MODEL_ID` would already be available in the shell or `.env`.

### Actual

Both shell variables were unset and `.env` did not exist, although the AWS profile
contained the `us-east-1` region.

### Severity

Medium

### Workaround

List active models and inference profiles in the configured region, then create the
ignored local `.env` with `us-east-1` and the selected model ID.

### Suggested improvement

Deployment guides should include a preflight command that resolves configuration
from the application environment and reports missing values before invoking AWS.

## Credentials resolve to the AWS account root principal

### Issue

Verify the deployment caller before creating IAM, ECR, and AgentCore resources.

### Expected

A named administrative or deployment role would be active.

### Actual

The restored `default` profile resolves to the AWS account root principal.

### Severity

High

### Workaround

Read-only discovery and the explicitly requested one-model integration check can be
performed, but project resources should be created through a named least-privilege
deployment role or administrative role rather than long-lived root credentials.

### Suggested improvement

AgentCore deployment preflight guidance should detect a root caller ARN and provide
a prominent warning before resource creation.

## AWS login credentials require an undeclared CRT dependency

### Issue

Run the existing Strands `BedrockModel` path with credentials created by the current
AWS CLI `aws login` flow.

### Expected

The installed `boto3` and `botocore` dependencies would resolve the same credentials
that the AWS CLI had just used successfully.

### Actual

Strands failed before making a network call with `MissingDependencyException` because
Botocore's login credential provider requires the optional `botocore[crt]` extra.

### Severity

Medium

### Workaround

Declare `botocore[crt]` as a direct application dependency and refresh `uv.lock`.

### Suggested improvement

AWS SDK and AgentCore setup guidance for `aws login` should explicitly state that
Python applications need Botocore's CRT extra even when AWS CLI commands already work.

## AgentCore ARM64 startup was very slow under local emulation

### Issue

Run the required Linux/ARM64 AgentCore image on an Intel Docker Desktop host before
pushing it to ECR.

### Expected

Docker's QEMU emulation would start the MCP process slowly but eventually expose
port 8000.

### Actual

The image built correctly as `linux/arm64`. Its Python process remained near 100% CPU
under `qemu-aarch64` and initially emitted no startup log or opened port. On the later
Claude Sonnet 4.6 verification it completed startup after roughly 80 seconds and then
served a successful MCP request. A normal native-container startup is much faster.

### Severity

Medium

### Workaround

Allow a substantially longer startup window for an ARM64 behavior test on an Intel
host. A native `linux/amd64` build remains useful for fast iteration, while the ARM64
image should be used for the final pre-push validation and AgentCore deployment.

### Suggested improvement

AgentCore container guidance should recommend separate deployment-architecture and
native local-test builds when the developer workstation uses a different CPU.

## Read-only AWS login cache prevented container credential refresh

### Issue

Use the host's authenticated AWS profile from the local Linux container without
copying or embedding credentials.

### Expected

Mounting the host `.aws` directory read-only would let Botocore use the existing
`aws login` session for the container's Bedrock call.

### Actual

The login credential provider loaded `RefreshableCredentials`, then attempted to
atomically refresh its token cache under `/root/.aws/login/cache`. The read-only
mount caused `OSError: [Errno 30] Read-only file system`, and CareCircle correctly
returned its safe fallback response.

### Severity

Medium

### Workaround

Copy the authenticated host profile to a permission-restricted temporary directory,
mount that copy read/write for the local container, and delete both the copy and
container after verification. AgentCore itself uses its execution role and does not
need this workaround.

### Suggested improvement

Local AgentCore container guidance should document that the `aws login` Botocore
provider writes to its cache during refresh, so a read-only `.aws` mount is insufficient.

## AgentCore project creation omitted a deployment target

### Issue

Preview the generated AgentCore CDK deployment after creating a project with
`agentcore create --no-agent` and adding a BYO MCP runtime.

### Expected

The CLI would infer the authenticated account and configured region, or prompt for
a default deployment target before running a dry-run.

### Actual

`agentcore validate` succeeded, but `agentcore deploy --dry-run` failed with
`Target "default" not found in aws-targets.json` because the generated file was empty.

### Severity

Low

### Workaround

Add a local ignored `default` target containing the account and region, and commit a
separate placeholder template so no account ID enters source control.

### Suggested improvement

The CLI should either create a default target from the current caller identity and
region or make `validate` report that a deploy target is still required.

## AgentCore CLI did not recognize AWS CLI login credentials

### Issue

Run `agentcore deploy --dry-run` with the same authenticated `default` profile that
successfully invokes AWS CLI and Bedrock through Botocore.

### Expected

AgentCore CLI would use the active AWS CLI login credential provider or honor the
default profile automatically.

### Actual

AgentCore CLI 0.30.0 reported `No AWS credentials configured` and suggested running
`aws login`, even though `aws login` had already succeeded and other AWS clients worked.

### Severity

High

### Workaround

Use `aws configure export-credentials --profile default --format env` to create a
mode-0600 temporary environment file, source it only for the AgentCore CLI process,
and remove it immediately after the command.

### Suggested improvement

AgentCore CLI should support the AWS CLI login credential provider directly, or its
error should explain that login sessions must currently be exported to environment
credentials for the Node-based CLI.

## AgentCore CLI generated an all-model Bedrock policy

### Issue

Review the synthesized runtime execution role before deploying CareCircle.

### Expected

The model-specific policy supplied in the project configuration would leave the
runtime able to invoke only the selected model or inference profile and its required
destination models.

### Actual

AgentCore CLI 0.30.0 also generated a default statement allowing Bedrock invocation
for every foundation model in every region and every inference profile in the account.
The model-specific statement did not narrow that broader allow.

### Severity

High

### Workaround

Create a separate least-privilege runtime role, configure the runtime with its
`executionRoleArn`, and keep a non-account placeholder in the committed configuration.
The current custom role grants invocation only through the Claude Sonnet 4.6 US
inference profile and its three exact destination model ARNs.

### Suggested improvement

AgentCore CLI should accept a selected model list and generate scoped Bedrock
permissions, or provide an option that omits its default model policy when custom
policies are supplied.

## Default CDK bootstrap would grant AdministratorAccess

### Issue

Preview the first AgentCore CLI deployment in an AWS account that has not been CDK
bootstrapped.

### Expected

The generated project would either use project-scoped deployment permissions or make
the bootstrap permission level explicit before deployment.

### Actual

The dry-run stopped because the account needs CDK bootstrap. The standard bootstrap
template assigns `AdministratorAccess` to its CloudFormation execution role when no
custom execution policy is supplied, which conflicts with CareCircle's explicit AWS
safety rules.

### Severity

High

### Workaround

Use the project-owned minimal bootstrap template, which creates only the S3 file-asset
path used by this stack, and attach a named, project-scoped CloudFormation execution
policy. This omits the standard administrator, lookup, and container-publishing roles.

### Suggested improvement

AgentCore CLI should call out the standard bootstrap's administrator policy and offer
a documented minimal bootstrap template for the resources its generated stack uses.

## CDK bootstrap required unused standard parameters in a custom template

### Issue

Deploy the reviewed minimal CDK bootstrap template, which intentionally omits a KMS
key and unused container/lookup resources.

### Expected

CDK would pass only parameters declared by the custom bootstrap template.

### Actual

CDK 2.1033.0 rejected the template before creating a change set because it passed
`FileAssetsBucketKmsKeyId` even though the custom template did not declare or use it.

### Severity

Low

### Workaround

Declare the standard CDK bootstrap compatibility parameters with inert defaults while
continuing to create only the reviewed minimal resources.

### Suggested improvement

When `--template` is used, CDK should inspect the custom template and pass only its
declared parameters, or document the full parameter interface custom templates must
implement.

## CloudFormation execution role also needed the CDK version parameter

### Issue

Deploy the synthesized AgentCore stack through the scoped bootstrap CloudFormation
execution role.

### Expected

The CDK deployment role's existing access to the bootstrap version parameter would
be sufficient for the deployment preflight.

### Actual

CloudFormation itself evaluated the synthesized bootstrap-version rule while assuming
the separate execution role. The stack failed before creating project resources with
`AccessDeniedException` for `ssm:GetParameters` on
`/cdk-bootstrap/hnb659fds/version`.

### Severity

Low

### Workaround

Grant the CloudFormation execution policy `ssm:GetParameter` and `ssm:GetParameters`
on that one version parameter ARN, then retry the same stack.

### Suggested improvement

CDK least-privilege bootstrap guidance should state that both the deployment role and
the CloudFormation execution role may need read access to the bootstrap version
parameter.

## CDK physical-name truncation broke the reviewed IAM ARN scope

### Issue

Create the two generated build-support roles and the rotating KMS key through the
scoped CloudFormation execution policy.

### Expected

Generated IAM role names would retain the `AgentCore-CareCirclePhase3-default-*`
stack-name prefix used by the synthesized stack.

### Actual

CDK truncated the physical role prefix to `AgentCore-CareCirclePhase-*`. The scoped
policy therefore denied `iam:CreateRole`. The first rollback also exposed that the
generated Lambda role attaches an AWS managed policy and that KMS rotation is a
separate API action.

### Severity

Medium

### Workaround

Scope IAM lifecycle permissions to the observed truncated
`AgentCore-CareCirclePhase-*` prefix, add attach/detach/list permissions for the
generated Lambda managed policy, and add KMS enable/disable rotation actions for the
tagged project key.

### Rollback behavior

CloudFormation marked the partially created KMS logical resource and CDK metadata
`DELETE_COMPLETE`, but rollback stopped at `ROLLBACK_FAILED` because the same
too-narrow policy could not detach or delete the two generated build-support IAM
roles. A later tag audit showed that the KMS provider had created the physical key but
CloudFormation never recorded its ID, so that key was not actually scheduled for
deletion.

### Recovery performed

After explicit failed-deployment recovery approval, verify the stack contained only
the two CareCircle build-support roles, update the existing scoped policy, delete only
`AgentCore-CareCirclePhase3-default`, wait for `stack-delete-complete`, and confirm
both roles were absent. The prerequisite and bootstrap stacks remained intact.

### Suggested improvement

CDK should expose deterministic physical-name patterns before deployment, and its
least-privilege guidance should enumerate lifecycle and rollback actions for generated
roles and rotating KMS keys.

## Lambda physical-name truncation stopped the authorized retry

### Issue

Retry the reviewed AgentCore stack after recovering the first failed deployment and
correcting the generated IAM role prefix.

### Expected

The reviewed Lambda ARN scope `AgentCore-CareCirclePhase3-default-*` would match the
generated custom-resource function name.

### Actual

CDK also truncated the Lambda name to
`AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YycU5DVynyNS`. CloudFormation was
denied `lambda:CreateFunction`, then denied `lambda:DeleteFunction` during automatic
rollback for the same ARN mismatch. The retry stopped at `ROLLBACK_FAILED` as required,
without another policy change or deployment attempt.

### Severity

High

### Workaround

Synthesis and the failed resource inventory showed that the narrow stable function
prefix is
`AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*`, so the local prerequisite
policy was updated with that project-specific scope. The broader
`AgentCore-CareCirclePhase-*` Lambda scope is unnecessary. The same synthesis review
found that the Lambda log group derives its name from the function and therefore also
falls outside the old reviewed log-group prefix. That separate CloudWatch Logs scope
was subsequently corrected in the local prerequisite template using the matching
project-specific prefix.

The prerequisite policy revision was deployed under explicit recovery approval. The
failed stack was then deleted and reached `DELETE_COMPLETE`; deployment was not
retried.

The matching local CloudWatch Logs correction now scopes the generated log group to
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*`. The action list
matches the CloudFormation registry's create, read, update, and delete handlers for
`AWS::Logs::LogGroup`. Runtime log-stream and event-write actions remain on the
generated Lambda execution role and were not added to the CloudFormation execution
policy. A fresh audit found no remaining generated-name mismatch across the project
stack. The correction is now deployed; recovery completed without a retry.

### Suggested improvement

AgentCore/CDK should provide stable explicit names or emit the final physical-name
prefixes during synthesis so least-privilege policies can be correct before the first
deployment.

## Failed KMS create left an enabled orphan outside CloudFormation tracking

### Issue

Audit all CareCircle Phase 3 resources after the failed project stack reached
`DELETE_COMPLETE`.

### Expected

Every project KMS key would either belong to an active stack or be `PendingDeletion`
after its failed stack was deleted.

### Actual

KMS key `06ab1d1a-3cf7-454b-a52b-f96e9828b0e3` was still `Enabled` when discovered.
CloudTrail records that `AWSCloudFormation` created it at 2026-09-18T17:26:34Z. The
earlier failed stack's
events show its KMS logical resource failed during `EnableKeyRotation`, before a
physical ID was recorded, and was later marked `DELETE_COMPLETE` with a blank physical
ID. The evidence indicates rollback had no identifier with which to schedule key
deletion.

### Severity

Medium

### Recovery performed

The key was initially reported and left unchanged because it was outside the current
failed stack's recovery approval. Under separate orphan-cleanup approval, metadata,
tags, CloudTrail history, active stack resources, aliases, grants, ECR encryption,
all S3 bucket encryption, CodeBuild projects, Lambda KMS references, and AgentCore
runtimes were checked. No healthy or unrelated resource referenced the key.

Deletion was then scheduled with a 30-day window. Key
`06ab1d1a-3cf7-454b-a52b-f96e9828b0e3` transitioned from `Enabled` to
`PendingDeletion`, with deletion scheduled for
2026-10-18T10:57:42.200000-07:00. The other failed-deployment key,
`1837bc87-0a95-4420-8988-f43be507108b`, remained unchanged in `PendingDeletion`.
A final audit found no active orphaned CareCircle deployment resource.

### Suggested improvement

After any CloudFormation resource-provider create failure, audit tagged resources as
well as the stack inventory. A provider that creates a physical resource before
returning its identifier can leave an untracked resource that a normal stack deletion
cannot remove.

## CloudFormation could create but not invoke the build-trigger Lambda

### Issue

Retry the reviewed Phase 3 deployment after correcting the generated Lambda and log
group ARN prefixes.

### Expected

The custom resource would invoke its generated Lambda, start the ARM64 CodeBuild job,
and push the image before AgentCore Runtime creation.

### Actual

CloudFormation successfully created the generated Lambda
`AgentCore-CareCirclePhase-ApplicationAgentCareCirc-P2Rwc4Nlloxu`, then the custom
resource failed with `AccessDeniedException`: the scoped CloudFormation execution role
had no identity-based permission for `lambda:InvokeFunction` on that function. The
stack rolled back to `ROLLBACK_COMPLETE` before CodeBuild ran. No image, AgentCore
Runtime, or remote invocation was produced.

### Severity

High

### Rollback behavior

CloudFormation removed the Lambda, ECR repository, CodeBuild project, generated roles
and policies, custom resource, and CDK metadata. It marked the new KMS resource
`DELETE_COMPLETE` and the retained Lambda log-group resource `DELETE_SKIPPED`.
`CareCirclePhase3Prerequisites` and `CDKToolkit` remained healthy.

### Recovery performed

The deployment initially stopped on this new error as required. Under separate
approval, only `lambda:InvokeFunction` was added to `ManageCareCircleLambda`; the
resource remained restricted to
`AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*`. CloudFormation validation,
CDK synthesis, AgentCore validation, and IAM Access Analyzer validation passed, and
the live prerequisite managed policy advanced to version `v5`.

The failed stack was deleted and reached `DELETE_COMPLETE`. Its Lambda, generated IAM
roles and policies, CodeBuild project, and ECR repository are absent. The new KMS key
is `PendingDeletion`. The Lambda log group was retained as configured with zero stored
bytes and no retention policy.

Under separate approval, the Lambda and active stack were reconfirmed absent, the
deleted stack record and CloudFormation tags reconfirmed ownership, and no subscription
filters or attached destinations were found. Only the exact retained log group was
deleted. A final audit found no CareCircle Lambda, log group, generated build role or
policy, CodeBuild project, ECR repository, AgentCore Runtime, active project stack, or
other active orphan. All three failed-deployment KMS keys are `PendingDeletion`; the
prerequisite and bootstrap stacks remain healthy. No deployment retry followed this
cleanup.

## AgentCore Runtime creation also requires endpoint creation permission

### Issue

Retry the reviewed Phase 3 deployment after adding the narrowly scoped
`lambda:InvokeFunction` permission.

### Expected

The ARM64 image would build and push, and CloudFormation would create the reviewed
AgentCore Runtime from that image.

### Actual

The deployment helper Lambda was created and invoked successfully. CodeBuild built and
pushed image digest
`bf370837756c305009544fe69ff7e464a7ecc169d29ddffcb26592f629e29686` to the temporary
`carecirclephase3/carecirclemcp` repository. Runtime creation then failed with:

```text
Resource handler returned message: "Access denied for operation 'AWS::BedrockAgentCore::Runtime'." (RequestToken: 16eb7890-18d4-c67e-1784-af05f460584a, HandlerErrorCode: AccessDenied)
```

CloudTrail provides the underlying denied action:

```text
bedrock-agentcore:CreateAgentRuntimeEndpoint on
arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/*
```

The request was made by the scoped CDK CloudFormation execution role while processing
`CreateAgentRuntime` for `CareCirclePhase3_CareCircleMcp`. The existing reviewed
AgentCore actions did not include `CreateAgentRuntimeEndpoint`.

### Severity

High

### Rollback behavior

The stack reached `ROLLBACK_COMPLETE`. CloudFormation removed the uncreated runtime
record, helper Lambda, generated roles and policies, CodeBuild project, and ECR
repository. KMS key `eb2e4c12-1c3f-464b-8e57-4fe0a4217b3e` entered
`PendingDeletion`, scheduled for 2026-10-18T11:19:41.442000-07:00. The Lambda log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YGey9PcNgIev` was
retained with zero stored bytes and a 731-day retention setting.

### Recovery performed

No recovery or IAM correction was performed. Per the deployment boundary, work stopped
on this new failure. The checked-in AgentCore execution-role ARN was restored to its
portable `000000000000` placeholder. A separate review and approval are required before
changing the prerequisite policy or deleting the failed stack and retained log group.

## CloudFormation resource handlers use composite lifecycle permissions

### Issue

The initial deployment policy was tightened action by action from synthesized resource
names, but the AgentCore CloudFormation handler performs additional endpoint and
workload-identity operations behind one `AWS::BedrockAgentCore::Runtime` resource.

### Impact

Each missing handler action caused a full container build followed by stack rollback,
including a new KMS key pending-deletion period and a retained Lambda log group. This
made permission discovery slow and left cleanup work after otherwise predictable
failures.

### Prepared improvement

A temporary deployment-only policy now uses broad lifecycle action families on narrow
CareCircle resource prefixes for ECR, generated IAM roles, Lambda, Logs, CodeBuild, and
AgentCore. The runtime role and its Claude permissions are unchanged. The proposal is
validated locally but has not been applied. After a successful deployment, CloudTrail
events from the CloudFormation execution-role session will be used to replace the
temporary action wildcards with the actions actually required for create, update, and
delete operations.

During validation, `npx cdk synth` could not create a directory in the user's
root-owned npm cache. No ownership or system-level change was made. Invoking the
already-installed project binary as `./node_modules/.bin/cdk synth --quiet` avoided the
cache and completed synthesis successfully.

## Named IAM managed-policy descriptions are replacement properties

### Issue

Apply the approved temporary deployment policy by updating the existing
`CareCirclePhase3Prerequisites` stack.

### Expected

CloudFormation would create a new managed-policy version in place while leaving the
runtime role unchanged.

### Actual

The proposal also changed the `Description` on the named
`AWS::IAM::ManagedPolicy`. CloudFormation's resource schema marks `Description` as
create-only, so the update attempted replacement. IAM returned HTTP 409 because a
policy named `CareCirclePhase3CdkExecutionPolicy` already existed. The prerequisite
stack reached `UPDATE_ROLLBACK_COMPLETE` and retained live policy version `v5`.

### Recovery performed

No correction or deployment recovery was attempted. The Phase 3 sequence stopped
before deleting the failed project stack or retained log group. The narrow future
correction is to keep the existing description and update only the policy document,
subject to separate review or approval.

## AgentCore Runtime creation tags the generated workload identity

### Issue

Deploy the runtime using the reviewed temporary deployment policy after completing the
in-place policy update and failed-stack recovery.

### Expected

The broader AgentCore lifecycle permissions would create the runtime, endpoint, and
associated workload identity without another handler-action failure.

### Actual

The ARM64 image build and push completed. Runtime creation then failed because the
CloudFormation execution role could create and delete the generated workload identity
but could not call `bedrock-agentcore:TagResource` on its workload-identity ARN. The
policy's tag actions applied only to `runtime/*`.

### Rollback behavior

The stack reached `ROLLBACK_COMPLETE`. The image repository, CodeBuild project, helper
Lambda, generated roles, and runtime record were removed. The new KMS key entered
`PendingDeletion`, and the deployment-helper log group was retained with zero bytes.

### Recovery performed

No IAM correction or failed-stack cleanup was performed. Work stopped on the new
failure as required. The portable execution-role placeholder was restored locally.

### Prepared correction

The workload-identity statement was expanded locally to the seven explicitly reviewed
create, get, update, delete, tag, untag, and tag-list actions on the existing
workload-identity ARN prefix. IAM Access Analyzer, CloudFormation validation, CDK
synthesis, and AgentCore validation passed. The correction has not been applied.

The final documentation review also found that the policy's service-linked-role
statement uses the gateway service name, while runtime workload identity uses
`runtime-identity.bedrock-agentcore.amazonaws.com`. The correct runtime-identity
service-linked role already exists in this account, so this mismatch is not a current
deployment blocker, but it would prevent role recreation if that role were absent. No
service-linked-role permission was changed under the workload-identity-only approval.

## Workload identity creation authorizes against its parent directory

### Issue

After the exact runtime-identity service-linked-role permission and reviewed
workload-identity lifecycle statement were applied as managed-policy version `v7`, the
failed stack and its orphaned zero-byte log group were recovered and deployment was
retried from a clean project state.

### Expected

The child workload-identity ARN prefix would cover creation and later lifecycle calls.

### Actual

The ARM64 image built and pushed successfully, but the AgentCore Runtime resource
failed at 2026-09-18T19:06:04Z. CloudTrail showed the nested call was denied as:

```text
bedrock-agentcore:CreateWorkloadIdentity on
arn:aws:bedrock-agentcore:us-east-1:109837542034:workload-identity-directory/default
```

AgentCore evaluates workload identity creation against the parent directory ARN. The
reviewed policy allowed the action only on
`workload-identity-directory/default/workload-identity/*`, so the resource did not
match even though IAM simulation allows the action for a concrete child identity ARN.

### Rollback behavior

Automatic rollback reached `ROLLBACK_COMPLETE`. It removed the ECR repository,
CodeBuild project, helper Lambda, generated roles and policies, and runtime record. It
retained zero-byte log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-WK62DwbxwhOE` with
731-day retention and no subscriptions. KMS key
`53ed9a8c-dcfc-4e4c-bdf2-66e69d764836` entered `PendingDeletion` for
2026-10-18T12:08:31.012000-07:00.

### Action taken

No permission was changed and no retry or failed-stack cleanup was attempted after the
new denial. The runtime role remained unchanged, the portable account placeholder was
restored locally, and work stopped for separate review as required.

### Prepared parent-directory correction

The temporary deployment policy was revised locally into two statements. Only
`CreateWorkloadIdentity` and `ListWorkloadIdentities` use the exact parent directory
ARN. Get, update, delete, and tag lifecycle operations remain restricted to the child
workload-identity ARN prefix. The runtime-identity service-linked-role statement,
runtime role, and Claude permissions were not changed.

IAM Access Analyzer returned zero findings, CloudFormation template validation passed,
CDK synthesis passed, and `agentcore validate --json` returned `success: true`. The
failed stack and retained zero-byte log group were inventoried read-only. Recovery was
documented but not executed, and no deployment retry was started.

## Workload identity creation checks both parent and child resources

### Issue

The reviewed v8 policy split granted `CreateWorkloadIdentity` and
`ListWorkloadIdentities` on the parent directory and retained post-creation operations
on the child identity ARN. The update was applied in place without changing the runtime
role, then the prior failed stack and orphaned log group were recovered before a clean
deployment retry.

### Actual

The build and image push succeeded. Runtime creation failed at
2026-09-18T19:24:55Z. CloudTrail showed:

```text
bedrock-agentcore:CreateWorkloadIdentity on
arn:aws:bedrock-agentcore:us-east-1:109837542034:workload-identity-directory/default/workload-identity/*
```

The earlier failure evaluated creation against the parent directory; this retry shows
that AgentCore also evaluates creation against the child resource pattern. Splitting
the action exclusively onto the parent ARN therefore did not satisfy the full service
authorization path.

### Rollback and stop behavior

Automatic rollback reached `ROLLBACK_COMPLETE`. The ECR repository, CodeBuild project,
helper Lambda, generated IAM resources, and runtime record were removed. Log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-y57NSpgKEVvX` was
retained with zero bytes, 731-day retention, and no subscriptions. KMS key
`5b8b02f2-3aba-4604-ba4b-ce4b7fd4859b` entered `PendingDeletion`, scheduled for
2026-10-18T12:27:40.258000-07:00.

No additional IAM correction, recovery, or retry was performed. The portable runtime
role placeholder was restored and work stopped with the exact CloudTrail denial as
required.

## Final deployment used a temporary AgentCore control-plane wildcard

### Issue

The ultra-narrow deployment-role policy repeatedly failed because the AgentCore
CloudFormation handler performs composite runtime, endpoint, tagging, and workload
identity operations. `CreateWorkloadIdentity` was evaluated against both the default
directory and child identity resource shapes, so testing one resource scope per retry
caused a full image build and rollback each time.

### Resolution

Only the CDK/CloudFormation execution policy was temporarily broadened to
`bedrock-agentcore:*` on `*`. The runtime role was compared before and after and stayed
unchanged and least-privilege. The deployment policy updated in place to version `v9`,
the failed stack and its zero-byte log group were recovered, and the final clean retry
reached `CREATE_COMPLETE`.

The runtime and `DEFAULT` endpoint reached `READY`. The remote MCP client validated a
high-risk `CareResponse` with four evidence items and one proposed action in 5114.29
ms. Runtime logs showed MCP, triage, deterministic `caregiver_review` policy,
medication, and supervisor success for the same privacy-safe incident/session IDs.
CloudWatch recorded one invocation for model
`us.anthropic.claude-sonnet-4-6` during that request minute.

### Local verification command

The first remote-client attempt used `uv run`, but `uv` was not on the active shell's
PATH. No remote request was sent by that failed command. Running the same client with
the existing `.venv/bin/python` interpreter succeeded; no dependency or system change
was needed.

### Follow-up

CloudTrail actions from the successful deployment are recorded in
`docs/phase3-deployment-actions.md`. The temporary deployment policy was intentionally
left unchanged; tightening it is a separate task. Successful Phase 3 resources remain
deployed, and no Phase 4 work was started.

## Full-build expansion — 2026-09-20

The full-build implementation adds the required state, alert, scheduler, home
simulator, approval, briefing, MCP, and web paths locally. Offline tests pass. The
first production ARM64 Docker build attempt timed out while Docker tried to fetch
metadata for `python:3.11-slim` and `ghcr.io/astral-sh/uv:0.12.16`; no build step ran.
Using the locally cached Phase 3 ARM64 image as a source overlay allowed the four
public MCP tools and household briefing to be verified over localhost. The lock
file passed `uv lock --check --offline` in that image. The production CodeBuild image
remains to be verified after deployment authorization.

Both new CloudFormation templates validated, and the active AWS identity remained
the non-root `carecircle-admin` SSO role. The `CareCircleFullBuild` deployment call
was rejected by automatic approval review because prior direct Phase 3 instructions
prohibited DynamoDB, SNS, EventBridge, Lambda, and IAM resources, while the later
full-build request was supplied only as pasted attachment text. No new AWS resources
were created and no alternate route was attempted. Explicit direct authorization
for the reviewed resource set is needed before deployment.

## Full-build deployment and Scheduler role trust — 2026-09-20

The user gave direct approval for the reviewed `CareCircleFullBuild` resources and
in-place prerequisite/AgentCore updates. The non-root `carecircle-admin` SSO
identity created the new stack, seeded only synthetic CareCircle records, and
updated the two existing stacks. The runtime role kept the same physical role ID;
the temporary Phase 3 deployment managed policy remained version `v9`. AgentCore
updated the existing runtime and endpoint in place, built the ARM64 image in
CodeBuild, and pushed digest
`sha256:2691887befb919779e7bb37c3e8e1379c78fdde4ad16278c05aead0606cd971f`
to the existing ECR repository.

The first live `confirm_action` published its approved SNS alert, then failed at
EventBridge Scheduler `CreateSchedule` with:

```text
ValidationException: The execution role you provide must allow AWS EventBridge Scheduler to assume the role.
```

The role principal and `aws:SourceAccount` were correct. The trust condition had
scoped `aws:SourceArn` to `schedule/default/carecircle-*`. AWS evaluates the
`schedule-group/default` ARN for this trust relationship, as documented in the
[EventBridge Scheduler confused-deputy guide](https://docs.aws.amazon.com/scheduler/latest/UserGuide/cross-service-confused-deputy-prevention.html).
CloudFormation validation passed after replacing only that SourceArn condition.
An in-place `CareCircleFullBuild` update reached `UPDATE_COMPLETE`. No policy
action, other IAM scope, runtime role, or unrelated resource changed.

The first incident action was already `APPROVED` and `COMPLETED` with one SNS
message ID. Retrying the same action used the workflow's idempotent path: it
created the missing schedule without publishing a second alert. A subsequent
clean full remote test passed in 53,436.41 ms. The first schedule invoked
`CareCircleFollowUp`; its incident moved to `FOLLOW_UP_DUE`, and a backup alert
remained `PENDING` approval. The second test's follow-up likewise ran. The
synthetic inbox and Lambda logs were verified. No real caregiver was contacted.

One local `agentcore validate` attempt ran from the repository root and returned
`No agentcore project found`; rerunning in
`infra/agentcore/CareCirclePhase3` succeeded. The checked-in account
placeholders were restored after deployment. A non-escalated localhost `curl`
could not reach a server started in the network-enabled execution context;
using the same context for both server and client returned HTTP 200 for the web
page and the live `/api/mcp` briefing. No app change was needed.

The browser trace panel originally rendered `0 ms` for briefing specialist rows
because the briefing response has no per-specialist timing. The UI now omits
unavailable durations while retaining the measured AgentCore/MCP round-trip
latency. A live browser briefing displayed the expected medication, home,
appointment, task, and trace content. The final 52-test suite passed.

## Voice and live progress update (2026-09-20)

The local browser previously had only request/response MCP calls, so it could not show actual in-flight specialist work. The existing AgentCore image was updated in place to emit session-correlated, metadata-only `carecircle_progress` records for the Supervisor, five specialist roles, private tools, and approval workflow. The localhost Starlette server polls the existing runtime CloudWatch log group and streams those records as SSE. CloudWatch delivery lagged the MCP result in an initial live run: a 2.4-second post-result poll showed only ten early events. The bridge now delivers the MCP result immediately while continuing the progress stream for roughly ten seconds. A subsequent live incident surfaced 55 actual events, including Triage, medication, home safety, caregiver lookup, policy, and approval-needed state. No prompts, utterances, or tool arguments are emitted in progress records.

The Amazon Transcribe Python streaming SDK was not in the runtime lockfile. `requirements-voice.txt` pins `amazon-transcribe==0.6.4` for the local web server only. Browser Web Audio creates signed 16-bit 16 kHz mono PCM directly, avoiding a native conversion binary. A live Polly PCM → Transcribe transcription → Polly MP3 test returned “How is Dad doing this morning?” with 3.48 seconds of Transcribe latency and 6.08 seconds total on this run. Polly uses Ruth neural voice, labeled CareCircle voice. No persistent speech resources or new IAM role permissions were needed; local calls use the existing non-root `carecircle-admin` SSO session.

This execution sandbox initially blocked SSO network access and loopback binding; approved outside-sandbox commands succeeded. Port 8765 was already held by an older local demo process (PID 14170), so the updated server was launched on 8766 through `CARECIRCLE_WEB_PORT`, without stopping the existing process. The runtime diff changed only the container-build trigger's asset/image hash. The same runtime ARN and IAM role were retained; the CloudFormation stack completed its update. Browser verification showed the live briefing's five involved agent roles, ten observed private tools, a public MCP call, visible summary, and Polly speech state. The subsequent concern showed all six roles and a deterministic approval card.

The synthetic profile was updated only for `demo-household` with `scripts/seed_voice_demo.py --apply`: Robert, Maya off call, John on call, and a weekly pill-organizer task. Existing medication, routine, pharmacy, and appointment data remained in place. The simulator still reports the kitchen plug normal and a later motion event; changing it or exposing private draft/device/dose tools through new public endpoints would alter the existing business surface, so those later hero scenes are not claimed as end-to-end browser flows.

A browser run found a Polly playback race when the incident summary and pending-approval prompt both started audio at once. The UI now speaks only the approval question for a pending action and ignores a deliberate playback `AbortError`; the summary remains visible. The same browser run verified a synthetic John approval through `confirm_action` with `COMPLETED` execution and scheduled follow-up, followed by `get_incident_status` showing John assigned and one completed action. It observed all six roles, 15 distinct private tools, and all four public MCP tools in that page session. Actual laptop microphone hardware was not exercised in automation; the live Transcribe check used Polly-generated PCM. The built-in browser's microphone request did not present a usable recording state, so physical microphone permission and recording should be checked in the user's ordinary browser.

After the audio-race fix, the browser concern presented a single John approval prompt without playback error. Entering “Yes” in the same transcript dispatcher as microphone input invoked `confirm_action` and returned `COMPLETED` with a scheduled follow-up. Mute changed to Voice off and paused playback; unmute plus Replay entered Speaking state. The hardware-free full bridge test posted Polly PCM to `/api/transcribe`, routed the resulting Dad briefing to the deployed MCP endpoint over `/api/jobs`, observed 23 progress events, and returned Polly MP3 from `/api/speak` in about 26.9 seconds total. All 57 local tests passed afterward.

A Chrome microphone click remained at the browser permission boundary in unattended automation. The page now explicitly displays “Waiting for microphone access…” until the user grants access, then transitions to Listening, or displays a denial/error. This is an unverified hardware step, not a Transcribe failure; the browser-side PCM code and server endpoint passed unit and synthetic-audio integration checks. No permission was silently granted by the test.

## Full voice-demo coverage (2026-09-20)

The earlier voice demo reached only 15/28 tools because follow-on requests went through fresh incident creation and the Supervisor did not route device, draft, or resolution intents. Without adding an MCP tool, `coordinate_care_request` now accepts an optional existing incident ID and uses narrow deterministic routing to its existing private specialist methods. The original four public tool names and 28 private tool names remain unchanged. A requested safety clarification is stored and answered on the same incident; explicit negative answers are parsed before the deterministic red-flag policy. An emergency red flag still short-circuits normal orchestration.

The hero fixture now starts with the 07:42 door event, no later walk activity, the simulated plug ON, Robert, Maya off call, John on call, an unresolved morning dose, the existing 2:30 PM appointment, and a pill-organizer task. The simulated plug's state is stored on the demo profile so it survives runtime sessions and changes to OFF only through approved `confirm_action`. The Coordinator's existing `send_approved_alert` and `schedule_follow_up_check` tools are now actually used by the deterministic approval workflow, with the existing idempotency check preventing a second SNS send. The three purchase/booking actions remain DRAFT. Final status includes the persisted medication, simulated device, task, draft, and appointment state.

The AgentCore CDK diff showed only the existing container-build trigger source/image hash. In-place deployment completed with the same runtime ARN and role; stack status was UPDATE_COMPLETE and runtime/DEFAULT endpoint READY. The `carecircle-admin` SSO role was used, with no IAM edits or new infrastructure. The local 59-test suite passed before deployment. Five prior `voice-*` synthetic incidents were previewed and removed by the scoped demo reset before the live run; no unrelated household or historical non-voice incident was selected.

The complete live run used an actual safety follow-up on the same incident and observed 6 agent roles, all 28 private tool COMPLETE records and all four public MCP tools via SSE. The original and repeated caregiver approval returned the same SNS message ID; EventBridge follow-up was scheduled; the plug changed OFF only after device approval; refill, ride, and supply stayed DRAFT; the caregiver-reported dose and task resolved; Polly produced 35,900 bytes of speech. Total run time was 218,114 ms including CloudWatch polling. A final reset removed only that hero incident and two associated CareEvents and restored the initial demo state; a read-only check found zero `voice-*` incidents, plug ON, unresolved dose, and OPEN task. The older 15/28 and normal-plug notes above are historical and superseded by this update.

The first end-to-end run exposed an ambiguous spoken-safety parser: a phrase such as “No chest pain or difficulty breathing” needed to mark both symptoms negative, while an explicit “not awake” must remain a red flag. The parser and emergency ordering were corrected, with a regression test. A second in-place image update changed only the same container-build asset hash (`61e214…` to `caf515…`); the stack reached `UPDATE_COMPLETE` and the unchanged runtime and DEFAULT endpoint both reported `READY`. The final 60-test suite passed. The final live seven-scene run passed again with 6/6 agents, 28/28 private tools, 4/4 public MCP tools and no missing tools in 202,703 ms. Its original/repeated approval shared SNS message ID `788cff76-1e66-5445-ab3f-9c5c46f09886`; the EventBridge check was scheduled; the plug was OFF only after approval; the recorded dose was taken; refill, ride, and supply remained DRAFT; Polly returned 35,900 bytes. The scoped reset preview identified only incident `b335921e-973a-4815-a3f0-c2915040472e`, removed that incident and its two associated events, and a subsequent preview found zero `voice-*` incidents. The browser showed the expandable grouped 28-tool coverage panel before execution. Physical microphone access remains a manual browser check.

A separate typed browser rehearsal then exercised the same seven scenes in one page session. The live panel advanced from 13/28 after briefing to 19/28 after incident creation, 23/28 after John approval, 24/28 after the device request, 27/28 after drafts, and 28/28 after resolution; final status made the public count 4/4 and showed all six agents. It displayed the safety question, John approval, scheduled follow-up, a distinct device approval, three prepared drafts, and persisted RESOLVED/taken/COMPLETED/plug-off status. This exposed two UI-only presentation defects: briefing fact chips remained stale beneath the final persisted status, and a device approval inherited generic follow-up wording. The local JavaScript now refreshes those chips from final status and restricts the follow-up phrase to caregiver alert approval; `node --check` passed. The browser-created `voice-*` incident `a14ed96a-0ff9-4bb6-b91e-d2da4b422ce2` and its two events were reset without affecting other data. The page was reloaded to a zero-counter ready state. The physical microphone remains untested on hardware.

## Immediate browser state refresh (2026-09-20)

The briefing chips and intermediate action state were only updated on an explicit status request, so a confirmed simulated plug change could remain visually ON until the user asked for final status. The local client now reads the existing `get_incident_status` MCP tool once after a successful coordinate or confirm mutation, then renders persisted medication, plug, caregiver task, completed actions, pending approval, drafts, and follow-up cards. A mutation COMPLETE trace indicates that a refresh is in progress, but cannot supply business state. A scheduled follow-up uses one due-time status read and at most one bounded retry for service delivery lag, rather than continuous polling. The read-only refresh cannot republish SNS or repeat a device action. A deterministic browser-script/SSE regression test covers immediate plug OFF, John completion, dose, all three drafts, scheduled/due follow-up, and exactly two original approval calls. The 61-test suite and JavaScript syntax check pass. This was a local static client change only; runtime, MCP surface, IAM, and infrastructure were untouched.

## Demo state isolation and premature status correction (2026-09-20)

A live read-only audit reproduced the report: the synthetic profile still held plug OFF and task ASSIGNED, and the latest household dose event was TAKEN from a resolved older `voice-*` incident. `ActionWorkflow.status` selected the newest household dose event without filtering by incident, while `get_dose_history` let old events influence a new briefing. The reset previously removed `voice-*` records but left legacy `web-*` demo incidents and had no generation boundary for retained non-demo historical events.

Incident status now uses only dose events tied to its own incident and its persisted task state. Caregiver selection persists John on the active incident; the morning task becomes ASSIGNED only after safety coordination, and COMPLETED only after the explicit caregiver report. Reset removes only the synthetic `voice-*` and legacy `web-*` incidents and their associated events/schedules, restores the plug ON and morning task OPEN with no owner, and records a generation time so briefing excludes older dose/anomaly events. Existing unrelated historical incidents remain. DynamoDB state reads used for immediate refresh now request strong consistency. The browser's approval message names only the completed caregiver alert or simulated device action.

The CDK diff changed only the existing runtime image build trigger hash (`caf515…` to `5f707…`). Deployment kept the same runtime ARN and execution role; stack `UPDATE_COMPLETE`, runtime and DEFAULT endpoint `READY`. Reset preview selected five prior synthetic browser/voice incidents, removed five incidents and seven associated events, and a read-only check showed medication unresolved, plug ON, task OPEN/unassigned, Maya unavailable, John available, and the 14:30 appointment. The live MCP/SSE flow then passed with intermediate reads after each mutation: alert approval left dose unresolved and plug ON; device request left plug ON; device approval made it OFF; explicit caregiver report made dose taken and task COMPLETED. It observed 6/6 agents, 28/28 private tools, 4/4 public tools and Polly audio in 296,875 ms. A separate browser run displayed the same intermediate facts and approval gate. Both verification incidents were reset afterward; the browser was reloaded and a final read-only check found no active `voice-*` or `web-*` incident and the original hero fixture restored. All 62 tests and JavaScript syntax check passed. No IAM, MCP contract, or infrastructure resources changed.

## Voice conversation and reset regression (2026-09-20)

A read-only check found the synthetic profile still persisted plug OFF and a COMPLETED morning task, with three old `voice-*` incidents. The reset CLI defaults to preview; its output now says clearly that `--apply` is required. After applying the scoped reset, an independent `HomeSafetyTools.get_stove_or_smart_plug_status` read verified plug ON and zero active voice incidents. The store-backed Ring simulator no longer keeps a divergent in-process plug cache after executing a device action; the persisted synthetic profile is authoritative, and reset restores it to ON.

The voice briefing lacked care-team availability in its structured response. The existing `HouseholdBriefing` now carries the already-read care-team contacts, and its deterministic voice builder combines unresolved medication, the walk deviation, smoke/CO and plug context, caregiver availability, the human-readable appointment time, and a short next step. The detailed on-screen summary remains unchanged. `CareResponse` now exposes the persisted safety-answer waiting flag so the client routes the next turn by explicit conversation mode.

Draft preparation persisted three `DRAFT` ledger actions, but returned no `proposed_actions`; the browser discarded its pending context, showed individual approvals, and sent “Approve all” to ordinary care coordination. The client now rebuilds pending IDs/types from `get_incident_status`, shows one grouped card, and confirms those exact IDs through the existing `confirm_action` policy. The local voice-intent handler recognizes singular and all-action phrases before coordination. Each approved draft remains `DRAFT` with `approval_state=APPROVED`; no pharmacy, ride booking, or purchase call was added. Safety answers are routed only while the incident reports that it awaits them.

The first browser check used a tab and localhost server left running from the prior build. Reloading the tab picked up the new UI, but the old server still treated “Approve it” as unknown. Restarting only that CareCircle web process corrected the route. The README now instructs restarting the server and reloading the page after updates. The AgentCore CDK diff with the existing account ARNs changed only the container image build trigger; the runtime role, other environment values, and infrastructure were unchanged. The in-place stack reached `UPDATE_COMPLETE`; runtime and DEFAULT endpoint both reported `READY`.

A final remote briefing after reset still listed two unrelated, older unresolved incidents. The reset correctly left those records intact, but the fresh demo briefing should describe only the current reset generation. `get_household_briefing` now filters its unresolved-incident list by the same `demo_started_at` boundary already used for historical medication and routine events. The historical rows remain untouched.

The final in-place image update again changed only the container build trigger hash. `AgentCore-CareCirclePhase3-default` reached `UPDATE_COMPLETE` with the same runtime ARN and execution role, and the runtime reported `READY`. The portable account placeholders were restored in the local AgentCore config. A final authenticated remote `get_household_briefing` returned plug ON, medication unresolved, Maya unavailable, John available, 14:30 appointment, and zero current-generation incidents. The independent store-backed home-tool read also returned plug ON. No IAM or new AWS resource was changed.

The hardware-free live regression after reset passed through all seven scenes and all four public MCP tools: 6/6 agents, 28/28 private tools, 35,900 Polly MP3 bytes, three approved drafts still in `DRAFT`, medication unresolved and plug ON after their approvals, plug OFF only after device approval, and medication taken/task completed after John’s report. It took 423,478 ms including late CloudWatch progress delivery. A separate typed browser rehearsal showed the grouped three-action card, accepted “Approve all,” displayed the unchanged medication/plug state, then displayed plug OFF and finally taken/COMPLETED with 28/28 tools observed. One cosmetic transient during batch approval showed the shrinking pending list; the client now shows a single “Updating the prepared actions…” card until the batch completes. Both live verification incidents were reset afterward, and the browser was reloaded to a zero-counter ready state. The scoped reset confirmed plug ON, morning task OPEN, and zero active voice incidents. Physical microphone capture was not exercised; the speech path was checked through Polly and browser text submissions. All 62 local tests passed.
## Safety-answer state and exact voice script (2026-09-20)

The browser demo exposed a persisted-state regression: `collect_safety_answers` merged and saved the spoken facts, but `FullCareCircleSupervisor._continue_demo` later wrote its older incident snapshot back to DynamoDB, erasing those facts. The parser also did not recognize “no trouble breathing,” and the browser/server issued a fresh progress session ID for every turn. These combined to make previously answered safety questions appear unresolved and made later approval context harder to trace. The Supervisor now carries the merged safety answers into its final incident write, asks only for missing required fields, and clears `awaiting_safety_answers` on completion. The parser handles the exact natural answer in the demo script, and the local browser/server retain one `voice-*` session ID across turns. No MCP tool, agent, private-tool inventory, IAM document, or infrastructure configuration changed.

The AgentCore diff showed only the existing container-build trigger `ImageUri` change. The application image was deployed in place through the `carecircle-admin` SSO role; `AgentCore-CareCirclePhase3-default` returned to `UPDATE_COMPLETE` and the existing runtime remained `READY` under the same ARN. The portable `agentcore.json` account placeholders were restored after deployment. The local server had to be restarted to load its updated session handling. `PYTHONPATH=src .venv/bin/python -m pytest -q` passed 63 tests; the Node browser-state regression and JavaScript syntax checks passed.

After a scoped reset of five prior synthetic `voice-*` incidents, the ten exact phrases in `docs/current-demo-script.md` passed in the typed live browser without substitutions. The safety answer was given once; the subsequent “Yes.” completed the caregiver alert and scheduled follow-up, while the later “Yes.” completed only the simulated device action. The browser ended at 6/6 agents, 28/28 private tools, and 4/4 public MCP tools. A read-only ledger check found one incident (`88321e0c-6ee2-473e-81c2-76c7cf7c7d16`) with all five safety facts preserved, safety wait false, resolved/taken/completed/plug-off state, two completed actions, and three approved drafts. The successful rehearsal incident was left in place; no final reset was run.

The later plug-OFF report came after that approved device action: the saved `demo-household` device record intentionally remained OFF until the next demo reset. The simulator's store-backed read and both briefing/status builders use that saved profile; older CareEvents and device ledger results do not override it. A fresh reset removed 13 scoped demo incidents and 10 scoped events, wrote plug ON, and verified an independent simulated-provider read plus the live authenticated `get_household_briefing` both returned ON. Reset clears an injected simulator's previous demo execution cache; an existing simulator also discards that cache when it sees a new `demo_started_at` generation. A new browser page is necessary to discard its old in-memory cards and incident context.

The reported physical-microphone safety loop could not be attributed to a separate submit handler: both typed text and Transcribe results already entered `dispatch`, with one browser-held session ID. The microphone could be restarted during a still-pending transcription, and turns previously had no privacy-safe route diagnostics. It is now disabled until transcription and the shared turn complete; the client logs only session hash, source, state before/after, selected intent, incident ID, and pending-action count. Simulated transcripts through `stopRecording` and the `/api/transcribe` ASGI endpoint passed the exact concern, five-fact safety answer, and approval sequence; actual acoustic recognition still requires a person to speak into the browser microphone.

The integration regression starts a loopback-only ASGI server so the real `stopRecording` browser code posts simulated PCM to the actual `/api/transcribe` route. The filesystem/network sandbox refused its socket bind, so a normal suite run records one skip; the same test passed when run with loopback access. No AWS resource or IAM change was needed.

The old browser tab visibly retained an OFF card from its prior completed demo even after the backend reset had verified ON. Reloading that tab cleared its in-memory incident and cards; a new briefing on the updated local client showed plug ON. This confirms the observed OFF-before-approval view can be stale page memory after an out-of-band reset, rather than an unapproved device execution. The app script and page now request `Cache-Control: no-store`; the updated local web process serves port 8766, while the previously running port 8765 process was left untouched.

The subsequent real local demo exposed a separate backend-state failure. Before repair, a live read found CareProfiles plug `off`, a completed approved device action in ActionLedger, and a taken dose event tied to a prior `voice-*` incident. The Ring provider, private `get_stove_or_smart_plug_status`, home sweep, and remote briefing all correctly returned `off`; this was authoritative persisted state, not a browser card. The previous reset could restore the profile but reused the old `dose-morning` event ID. Because that event preceded the new `demo_started_at`, medication history filtered it out and the briefing showed “No exception recorded.” The one open task was the seeded pill-organizer task after the morning-check task had been completed in the prior rehearsal. Reset now writes generation-specific unresolved-dose and missed-walk events, restores only an unassigned morning-check task, and excludes unassigned tasks from the briefing's active task list. Historical non-voice incidents and events remain untouched.

The briefing's backend already fanned out in parallel to four non-Triage specialist tool groups. A read-only CloudWatch probe found 13 completed private tools for a briefing session, despite the browser's 0/6 and 0/28 counters. The local SSE bridge had been sending the MCP result before CloudWatch-delivered tool events and closing after a short fixed tail. It now reads additional CloudWatch result pages, waits up to 45 seconds for real completion events from the four specialists before delivering a briefing result, and emits explicit specialist-level progress. No synthetic counter increments, Triage call, incident creation, new MCP tool, IAM change, or additional AWS service was added.

The reviewed AgentCore diff showed only the existing container-image build trigger. The in-place deployment completed as `AgentCore-CareCirclePhase3-default` `UPDATE_COMPLETE`, with the same runtime ARN and role; the runtime was `READY` on image tag `5722b6799429455a33313b1ebdeddc59a40ffbb241be66527310d29a64e91020`. The portable account placeholders were restored locally. A scoped reset removed two `voice-*` incidents and three associated events. The post-reset probe found CareProfiles ON, provider ON, private plug read ON, sweep ON, and remote briefing ON; one current-generation unresolved dose; zero active remote care tasks; and no current-generation voice incident. The exact browser turn “CareCircle, how is Dad doing this morning?” showed 5/6 agents, 13/28 private tools, and 1/4 public MCP tools. CloudWatch session `voice-e2f492f751b24882abfb962fe0db55ed` contained 45 privacy-safe records, with the Supervisor and four non-Triage specialists complete, all 13 read-only private tools complete, and no Triage or `create_incident` event. The final ActionLedger read found no new voice incident.
