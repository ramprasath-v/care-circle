# CareCircle Phase 3 AWS resource review

This began as the approval boundary for the first deployment in `us-east-1`. The
prerequisite and minimal bootstrap stacks are deployed. The matching Lambda and
Lambda log-group scopes were deployed to the prerequisite policy, and the earlier
failed AgentCore project stack was recovered to `DELETE_COMPLETE` on 2026-09-18. An
approved retry later that day stopped at `ROLLBACK_COMPLETE` because the scoped
CloudFormation execution policy did not allow `lambda:InvokeFunction` on the generated
container-build custom-resource Lambda. The single missing action was subsequently
added on the existing project-specific ARN, and the failed stack was deleted. No
further deployment retry has run.
All taggable project resources use `Project=CareCircle` and
`Environment=Hackathon`.

The failed retry's Lambda, generated roles and inline policies, CodeBuild project, and
ECR repository are gone. Its Lambda log group was never created. Its KMS key is
`PendingDeletion`. The post-recovery audit also found one enabled KMS key left by the
earlier failed stack attempt; after a separate ownership and non-use review, that
orphan was also scheduled for deletion with a 30-day window.

The verified deployment caller is the `ram-admin` session of the
`AWSReservedSSO_AdministratorAccess_fa2d2b5b096695c5` role through profile
`carecircle-admin`. The active model is the `ACTIVE`, system-defined US inference
profile `us.anthropic.claude-sonnet-4-6`.

## Prerequisite stack: `CareCirclePhase3Prerequisites`

Source: `iam/phase3-prerequisites.yaml`

- One IAM role named `CareCirclePhase3AgentCoreRuntimeRole`.
- One IAM managed policy named `CareCirclePhase3CdkExecutionPolicy`.

The runtime role trusts only `bedrock-agentcore.amazonaws.com`, with source-account
and AgentCore source-ARN conditions. Its inline policy allows:

- `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` only on:
  - `arn:aws:bedrock:us-east-1:<AWS_ACCOUNT_ID>:inference-profile/us.anthropic.claude-sonnet-4-6`
  - `arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6`
  - `arn:aws:bedrock:us-east-2::foundation-model/anthropic.claude-sonnet-4-6`
  - `arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-6`
  These are the profile ARN and the three exact destination model ARNs currently
  returned by `GetInferenceProfile`. There is no wildcard Bedrock resource grant.
- ECR layer reads only from `carecirclephase3/carecirclemcp`.
- `ecr:GetAuthorizationToken` on `*`; ECR does not support resource scoping for this
  action.
- CloudWatch Logs discovery and writes only under
  `/aws/bedrock-agentcore/runtimes/*`.
- X-Ray trace and sampling actions on `*`; these APIs do not support useful resource
  scoping.
- `cloudwatch:PutMetricData` on `*`, conditioned to the `bedrock-agentcore`
  namespace; CloudWatch metrics do not support resource ARNs.

The CDK execution managed policy contains the exact CloudFormation-time actions in
the source template. It is scoped to the CareCircle ECR repository, tagged KMS key,
generated stack role/function/log names (including CDK's truncated
`AgentCore-CareCirclePhase-*` IAM role prefix), one CodeBuild project, AgentCore runtime
resources in `us-east-1`, the CareCircle CDK asset bucket, and read access to the
single `/cdk-bootstrap/hnb659fds/version` parameter required by CloudFormation's CDK
bootstrap-version rule.

## Minimal CDK bootstrap stack: `CDKToolkit`

Source: `cdk-bootstrap.yaml`

- One versioned, private S3 asset bucket with AES-256 server-side encryption,
  30-day noncurrent-version cleanup, and one-day incomplete-upload cleanup.
- One S3 bucket policy that denies non-TLS access.
- One file-publishing IAM role and one inline policy scoped to that bucket.
- One CDK deployment IAM role and one inline policy scoped to the
  `AgentCore-CareCirclePhase3-default` CloudFormation stack, its change sets, the
  asset bucket, bootstrap version parameter, and the execution role it may pass.
- One CloudFormation execution IAM role with only
  `CareCirclePhase3CdkExecutionPolicy` attached.
- One SSM parameter at `/cdk-bootstrap/hnb659fds/version`.

This template deliberately omits the standard bootstrap's `AdministratorAccess`,
account-wide lookup role, ECR asset repository, image-publishing role, and bootstrap
customer-managed KMS key. The synthesized project has only file assets, so those
resources are unnecessary.

## AgentCore project stack: `AgentCore-CareCirclePhase3-default`

Synthesized from the AgentCore CLI 0.30.0 configuration after importing the runtime
role:

- One customer-managed KMS key with annual rotation for ECR encryption.
- One private ECR repository named `carecirclephase3/carecirclemcp`, with scan on
  push, KMS encryption, delete-on-stack-removal behavior, and a lifecycle rule that
  retains the newest 10 images.
- One CodeBuild project named
  `AgentCore-CareCirclePhase3-default-container-builder`, using
  `BUILD_GENERAL1_SMALL`, `ARM_CONTAINER`, and
  `aws/codebuild/amazonlinux-aarch64-standard:3.0`, with a 30-minute timeout.
- One CodeBuild IAM role and inline policy. It may get an ECR token, write
  `/aws/codebuild/*` logs, push and pull only the CareCircle ECR repository, and read
  only the CareCircle CDK asset bucket.
- One Node.js 22 Lambda custom-resource function with a 15-minute timeout, plus its
  log group retained for 731 days.
- One Lambda IAM role with AWS-managed `AWSLambdaBasicExecutionRole` and an inline
  policy limited to starting and polling the one CareCircle CodeBuild project. The
  managed policy is used by the generated AgentCore build trigger solely to write its
  Lambda logs.
- One CloudFormation custom resource that runs the CodeBuild image build and push.
- One `AWS::BedrockAgentCore::Runtime` named
  `CareCirclePhase3_CareCircleMcp`, configured for MCP, public networking, AWS IAM
  inbound authorization, 300-second idle timeout, and 900-second maximum lifetime.
- One service-managed workload identity associated automatically with the new runtime.
  The account's required `AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` already
  exists, so this deployment will not create another service-linked role.
- Runtime environment variables: `AWS_REGION=us-east-1`,
  `BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6`,
  `SUPERVISOR_TIMEOUT_SECONDS=60`, and `LOG_LEVEL=INFO`.
- One CDK metadata record, which has no runtime capacity or application behavior.

The AgentCore stack imports `CareCirclePhase3AgentCoreRuntimeRole`; it does not create
the CLI's default all-model runtime role or its default policies.

## Services that may incur cost

- AgentCore Runtime: active CPU and peak-memory consumption for each remote session.
- Amazon Bedrock: Claude Sonnet 4.6 input and output tokens through the US inference
  profile.
- CodeBuild: ARM small build minutes during deployment.
- ECR: stored image bytes; same-region pulls do not add transfer charges.
- KMS: one customer-managed key, billed monthly and prorated while it exists, plus
  request charges above applicable free usage.
- S3: small CDK source and template artifacts.
- CloudWatch/X-Ray: low-volume deployment and runtime logs, metrics, and traces.
- Lambda: one deployment-time build trigger; expected usage is seconds/minutes and
  may fall within account free usage.

For a single deployment and one verification request, variable consumption should be
small. The customer-managed KMS key is the clearest recurring fixed charge until the
project stack is deleted; ECR and S3 storage continue until their artifacts are
removed.

## Verification completed before approval

- `aws sts get-caller-identity --profile carecircle-admin` returned the expected SSO
  administrator role session.
- `GetInferenceProfile` returned `ACTIVE` for Claude Sonnet 4.6 and the three model
  destinations listed above.
- The live CareCircle triage path succeeded with Claude Sonnet 4.6 in 4.72 seconds.
- All 35 unit/in-process integration tests passed.
- The tested image reports `linux/arm64` and starts `carecircle`.
- The ARM64 container started under local emulation and completed an MCP request using
  Claude Sonnet 4.6. The validated result was high risk with four evidence items and
  one proposed caregiver action; privacy-safe logs showed successful triage,
  medication, deterministic policy, and supervisor completion.

## Narrow Lambda recovery review

The failed deployment rejected `lambda:CreateFunction`, and rollback then rejected
`lambda:DeleteFunction`, for this generated function ARN:

```text
arn:aws:lambda:us-east-1:<AWS_ACCOUNT_ID>:function:AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YycU5DVynyNS
```

The original reviewed resource scope was:

```text
arn:aws:lambda:us-east-1:<AWS_ACCOUNT_ID>:function:AgentCore-CareCirclePhase3-default-*
```

The revised resource scope is:

```text
arn:aws:lambda:us-east-1:<AWS_ACCOUNT_ID>:function:AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
```

The synthesized Lambda logical ID is
`ApplicationAgentCareCircleMcpContainerImageBuilderContainerBuildHandler68D85EBB`.
Its `AWS::Lambda::Function` has no `FunctionName` property, so CloudFormation creates
the physical name from the stack name and logical ID, truncating both before adding a
generated suffix. The failed stack proves the resulting stable prefix is
`AgentCore-CareCirclePhase-ApplicationAgentCareCirc-`. This prefix is narrower than
`AgentCore-CareCirclePhase-*`: it covers only the CareCircle stack's container-build
custom-resource function and its generated suffix. It does not cover unrelated
Lambda functions or even other generated functions in a CareCircle stack.

The exact revised statement is:

```yaml
- Sid: ManageCareCircleLambda
  Effect: Allow
  Action:
    - lambda:AddPermission
    - lambda:CreateFunction
    - lambda:DeleteFunction
    - lambda:GetFunction
    - lambda:GetFunctionConfiguration
    - lambda:ListTags
    - lambda:RemovePermission
    - lambda:TagResource
    - lambda:UntagResource
    - lambda:UpdateFunctionCode
    - lambda:UpdateFunctionConfiguration
  Resource: !Sub arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
```

`lambda:ListTags` remains because the synthesized function carries the project and
environment tags and CloudFormation reconciles those tags during its lifecycle. No
Lambda action or non-Lambda permission was added.

## Matching Lambda log-group scope correction

The Lambda log group's logical ID is
`ApplicationAgentCareCircleMcpContainerImageBuilderContainerBuildHandlerLogGroup1DFDB90E`,
and its synthesized `LogGroupName` is `/aws/lambda/` joined to a `Ref` of the Lambda.
Its physical pattern is therefore:

```text
/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
```

The original reviewed CloudWatch Logs scope expected
`/aws/lambda/AgentCore-CareCirclePhase3-default-*`. The revised scope is the matching,
project-specific log-group prefix above. The exact revised statement is:

```yaml
- Sid: ManageCareCircleLambdaLogs
  Effect: Allow
  Action:
    - logs:CreateLogGroup
    - logs:DeleteLogGroup
    - logs:DeleteRetentionPolicy
    - logs:DescribeLogGroups
    - logs:ListTagsForResource
    - logs:PutRetentionPolicy
    - logs:TagResource
    - logs:UntagResource
  Resource: !Sub arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
```

The live CloudFormation registry schema for `AWS::Logs::LogGroup` lists these actions
across its create, read, update, and delete handlers. The synthesized resource has a
name, 731-day retention, and tags, and both its deletion and replacement policies are
`Retain`. Keeping the complete handler lifecycle set also supports CloudFormation
rollback without adding stream or event-write permissions. `logs:CreateLogStream`,
`logs:DescribeLogStreams`, and `logs:PutLogEvents` are runtime concerns already
provided to the generated Lambda execution role by its synthesized
`AWSLambdaBasicExecutionRole`; they are not duplicated in the CloudFormation
execution policy. IAM Access Analyzer returned no findings for this exact scoped
statement. No Logs statement uses `Resource: "*"`.

## Generated-name audit after both corrections

No generated-name mismatch remains in the synthesized stack:

- Lambda: the corrected function scope matches the observed generated physical
  prefix.
- CloudWatch Logs: the corrected log-group scope is `/aws/lambda/` plus that Lambda
  prefix.
- CodeBuild: the synthesized explicit name remains
  `AgentCore-CareCirclePhase3-default-container-builder` and matches its exact scope.
- ECR: the synthesized explicit repository name remains
  `carecirclephase3/carecirclemcp` and matches its exact scope.
- IAM roles: both generated physical names use the reviewed
  `AgentCore-CareCirclePhase-*` prefix. Their `AWS::IAM::Policy` resources are inline
  policies attached to those roles and do not require separate managed-policy ARNs.
- KMS: the key has no generated name dependency; its lifecycle permissions remain
  restricted by the `Project=CareCircle` and `Environment=Hackathon` tags.
- AgentCore Runtime: the explicit name remains
  `CareCirclePhase3_CareCircleMcp`, within the reviewed regional runtime scope.
- Custom resource: it has no independent generated service resource name; its
  service token directly references the corrected Lambda ARN.

No Bedrock, IAM, ECR, S3, CodeBuild, KMS, or AgentCore permission changed during this
correction.

## Failed-stack recovery executed

Recovery was limited to the failed `AgentCore-CareCirclePhase3-default` stack:

1. Reconfirm that the stack is still `ROLLBACK_FAILED` and list every owned resource.
2. Confirm the list contains only the failed CareCircle Phase 3 resources and does
   not include `CareCirclePhase3Prerequisites`, `CDKToolkit`, unrelated resources, or
   manually existing resources.
3. Deploy the reviewed prerequisite-policy revision so the current custom-resource
   Lambda can be deleted by CloudFormation.
4. Delete only `AgentCore-CareCirclePhase3-default`, wait for
   `stack-delete-complete`, and verify its failed build-support Lambda, roles,
   policies, CodeBuild project, ECR repository, and KMS key were removed according to
   their stack deletion policies.
5. Verify `CareCirclePhase3Prerequisites` and `CDKToolkit` remain intact.
6. Keep retry as a separate operation requiring explicit approval.

The prerequisite update reached `UPDATE_COMPLETE`; managed-policy version `v4`
contains exactly the reviewed Lambda and Logs resource prefixes. CloudFormation then
deleted only the failed project stack and reported `DELETE_COMPLETE` at
2026-09-18T17:50:19.962Z.

The executed recovery and verification sequence was:

```bash
aws cloudformation describe-stacks \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name AgentCore-CareCirclePhase3-default

aws cloudformation list-stack-resources \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name AgentCore-CareCirclePhase3-default

aws cloudformation deploy \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name CareCirclePhase3Prerequisites \
  --template-file infra/iam/phase3-prerequisites.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --tags Project=CareCircle Environment=Hackathon

aws cloudformation delete-stack \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name AgentCore-CareCirclePhase3-default

aws cloudformation wait stack-delete-complete \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name AgentCore-CareCirclePhase3-default

aws lambda get-function \
  --profile carecircle-admin \
  --region us-east-1 \
  --function-name AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YycU5DVynyNS

aws iam get-role \
  --profile carecircle-admin \
  --role-name AgentCore-CareCirclePhase-ApplicationAgentCareCircl-JU9iNJWQHbS5

aws iam get-role \
  --profile carecircle-admin \
  --role-name AgentCore-CareCirclePhase-ContainerBuildProjectCont-kLLS38EiUbOQ

aws codebuild batch-get-projects \
  --profile carecircle-admin \
  --region us-east-1 \
  --names AgentCore-CareCirclePhase3-default-container-builder

aws ecr describe-repositories \
  --profile carecircle-admin \
  --region us-east-1 \
  --repository-names carecirclephase3/carecirclemcp

aws kms describe-key \
  --profile carecircle-admin \
  --region us-east-1 \
  --key-id 1837bc87-0a95-4420-8988-f43be507108b

aws cloudformation describe-stacks \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name CareCirclePhase3Prerequisites

aws cloudformation describe-stacks \
  --profile carecircle-admin \
  --region us-east-1 \
  --stack-name CDKToolkit
```

After deletion, the Lambda and IAM lookups must return `NotFound`; the CodeBuild and
ECR results must show no matching resource. The KMS key is expected to enter
`PendingDeletion` because CloudFormation schedules customer-managed key deletion
rather than destroying key material immediately. The two inline IAM policies are
removed with their owning roles. A future deployment retry is deliberately omitted
from this command set.

## Recovery result and orphan audit

- `AgentCore-CareCirclePhase3-default`: `DELETE_COMPLETE`.
- `CareCirclePhase3Prerequisites`: `UPDATE_COMPLETE`, with its runtime role and scoped
  CDK execution managed policy intact.
- `CDKToolkit`: `CREATE_COMPLETE`, with all seven bootstrap resources intact.
- Removed: generated Lambda
  `AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YycU5DVynyNS`, both generated
  build-support IAM roles and their inline policies, CodeBuild project
  `AgentCore-CareCirclePhase3-default-container-builder`, and ECR repository
  `carecirclephase3/carecirclemcp`.
- No Lambda log group matching
  `/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*` exists. The
  failed deployment did not create one.
- KMS key `1837bc87-0a95-4420-8988-f43be507108b` is `PendingDeletion`, scheduled for
  2026-10-18T17:50:35.788Z.
- No CareCircle Phase 3 Lambda, generated IAM role, CodeBuild project, ECR repository,
  AgentCore Runtime, or matching CloudWatch log group remains.

The tag audit found one orphan from the earlier failed stack attempt: KMS key
`06ab1d1a-3cf7-454b-a52b-f96e9828b0e3` was `Enabled`. CloudTrail records `CreateKey`
by `AWSCloudFormation` at 2026-09-18T17:26:34Z. The earlier stack recorded the key
resource as `CREATE_FAILED` because `EnableKeyRotation` was denied, with no physical
ID, and later marked that logical resource `DELETE_COMPLETE` with the physical ID
still blank. The evidence indicates CloudFormation created the key but lost the
physical identifier before rollback, so it could not schedule that key for deletion.

Before cleanup, the key's tags identified `Project=CareCircle`,
`Environment=Hackathon`, `agentcore:project-name=CareCirclePhase3`, and
`agentcore:target-name=default`. It had no aliases or grants. No active CloudFormation
stack owned it; the two CareCircle healthy stacks contained no KMS resource. ECR and
all S3 buckets used AES-256 rather than this key, there were no CodeBuild projects or
Lambda KMS references, and the only unrelated AgentCore runtime had no KMS reference.

Under separate orphan-cleanup approval, deletion was scheduled with the same 30-day
window used for the recent failed-stack key. Key
`06ab1d1a-3cf7-454b-a52b-f96e9828b0e3` transitioned from `Enabled` to
`PendingDeletion`, with deletion scheduled for
2026-10-18T10:57:42.200000-07:00. Key
`1837bc87-0a95-4420-8988-f43be507108b` remains unchanged in `PendingDeletion`, with
deletion scheduled for 2026-10-18T10:50:35.788000-07:00.

The final read-only audit found no CareCircle project stack, Lambda, generated IAM
role, CodeBuild project, ECR repository, AgentCore Runtime, or matching Lambda log
group. `CareCirclePhase3Prerequisites` remains `UPDATE_COMPLETE`, and `CDKToolkit`
remains `CREATE_COMPLETE`. At that checkpoint no orphaned active CareCircle deployment
resource remained, and the environment was ready for the subsequently approved retry.

## Latest deployment retry stopped on custom-resource invocation

The approved retry created the reviewed KMS key, ECR repository, CodeBuild project,
generated roles and policies, custom-resource Lambda, and Lambda log-group resource.
CloudFormation then failed before the CodeBuild image build because its execution role
could not invoke the custom-resource Lambda:

```text
User: arn:aws:sts::109837542034:assumed-role/cdk-hnb659fds-cfn-exec-role-109837542034-us-east-1/AWSCloudFormation is not authorized to perform: lambda:InvokeFunction on resource: arn:aws:lambda:us-east-1:109837542034:function:AgentCore-CareCirclePhase-ApplicationAgentCareCirc-P2Rwc4Nlloxu because no identity-based policy allows the lambda:InvokeFunction action
```

The stack reached `ROLLBACK_COMPLETE`. CloudFormation removed the ECR repository,
Lambda, CodeBuild project, generated roles and policies, CDK metadata, and custom
resource. It marked the KMS resource `DELETE_COMPLETE` and the retained Lambda log
group resource `DELETE_SKIPPED`. No image was built or pushed, no AgentCore Runtime
was created, and no remote invocation occurred. `CareCirclePhase3Prerequisites`
remains `UPDATE_COMPLETE`; `CDKToolkit` remains `CREATE_COMPLETE`.

This was a new least-privilege permission gap. The failed invocation used the already
reviewed project-specific Lambda prefix, but `lambda:InvokeFunction` was absent from
the Lambda action list.

Under separate approval, only `lambda:InvokeFunction` was added to
`ManageCareCircleLambda`; its resource remains:

```text
arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
```

CloudFormation validation, CDK synthesis, AgentCore validation, and IAM Access
Analyzer validation all passed; Access Analyzer returned no findings. The prerequisite
stack reached `UPDATE_COMPLETE`, and live managed-policy version `v5` confirms the one
added action with the unchanged resource scope.

The failed `AgentCore-CareCirclePhase3-default` stack reached `DELETE_COMPLETE` at
2026-09-18T18:09:17.886Z. Its Lambda, generated IAM roles and inline policies,
CodeBuild project, and ECR repository are absent. KMS key
`d8b9c076-597a-4412-b624-b246fd6b9bea` is `PendingDeletion`, scheduled for
2026-10-18T11:03:04.439000-07:00. `CareCirclePhase3Prerequisites` remains
`UPDATE_COMPLETE`, and `CDKToolkit` remains `CREATE_COMPLETE`.

The retained Lambda log group physically existed after rollback:

```text
/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-P2Rwc4Nlloxu
```

It contained zero stored bytes and had no retention policy. Before deletion, the
corresponding Lambda and active project stack were confirmed absent; the deleted stack
record and CloudFormation tags confirmed ownership by the failed CareCircle Phase 3
deployment; and the log group had no subscription filters or attached destinations.

Under separate approval, only that exact log group was deleted. The final read-only
audit found:

- no active `AgentCore-CareCirclePhase3-default` stack;
- `CareCirclePhase3Prerequisites` at `UPDATE_COMPLETE`;
- `CDKToolkit` at `CREATE_COMPLETE`;
- no CareCircle Lambda, Lambda log group, generated build role or policy, CodeBuild
  project, ECR repository, or AgentCore Runtime;
- all three failed-deployment KMS keys in `PendingDeletion`:
  - `06ab1d1a-3cf7-454b-a52b-f96e9828b0e3`, deletion scheduled for
    2026-10-18T10:57:42.200000-07:00;
  - `1837bc87-0a95-4420-8988-f43be507108b`, deletion scheduled for
    2026-10-18T10:50:35.788000-07:00;
  - `d8b9c076-597a-4412-b624-b246fd6b9bea`, deletion scheduled for
    2026-10-18T11:03:04.439000-07:00.

The tag audit now contains only the two healthy support stacks and their expected
bootstrap resources, plus the three keys pending deletion. No active orphaned
CareCircle deployment resource remains. The environment is fully clean and ready for
a separately approved Phase 3 deployment retry; no retry was performed.

## 2026-09-18 retry result: AgentCore Runtime endpoint permission denied

The approved retry passed the identity and inference-profile preflight, created and
invoked the reviewed deployment helper Lambda, and completed the ARM64 CodeBuild job.
The custom resource reported this pushed image URI:

```text
109837542034.dkr.ecr.us-east-1.amazonaws.com/carecirclephase3/carecirclemcp:bf370837756c305009544fe69ff7e464a7ecc169d29ddffcb26592f629e29686
```

CloudFormation then failed logical resource
`ApplicationAgentCareCircleMcpRuntime0726CFFB` at 2026-09-18T18:16:57.100Z:

```text
Resource handler returned message: "Access denied for operation 'AWS::BedrockAgentCore::Runtime'." (RequestToken: 16eb7890-18d4-c67e-1784-af05f460584a, HandlerErrorCode: AccessDenied)
```

The matching CloudTrail `CreateAgentRuntime` event gives the actionable denial:

```text
User: arn:aws:sts::109837542034:assumed-role/cdk-hnb659fds-cfn-exec-role-109837542034-us-east-1/AWSCloudFormation is not authorized to perform: bedrock-agentcore:CreateAgentRuntimeEndpoint on resource: arn:aws:bedrock-agentcore:us-east-1:109837542034:runtime/* because no identity-based policy allows the bedrock-agentcore:CreateAgentRuntimeEndpoint action
```

No policy was changed and no retry followed. Any correction must be separately reviewed
and approved; the likely correction is limited to the named action within the existing
project runtime resource scope, but this document does not authorize that mutation.

Automatic rollback completed at 2026-09-18T18:19:51.514Z. Current state:

- `AgentCore-CareCirclePhase3-default`: `ROLLBACK_COMPLETE` (failed stack retained).
- `CareCirclePhase3Prerequisites`: `UPDATE_COMPLETE`.
- `CDKToolkit`: `CREATE_COMPLETE`.
- Runtime logical resource: `DELETE_COMPLETE`, with no physical runtime ID assigned.
- ECR repository `carecirclephase3/carecirclemcp`: absent after rollback.
- CodeBuild project `AgentCore-CareCirclePhase3-default-container-builder`: absent.
- Helper Lambda and both generated build roles: absent.
- KMS key `eb2e4c12-1c3f-464b-8e57-4fe0a4217b3e`: `PendingDeletion`, scheduled for
  2026-10-18T11:19:41.442000-07:00.
- Retained log group
  `/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YGey9PcNgIev`:
  present, zero stored bytes, 731-day retention.

Because the runtime was never created, no authenticated remote MCP invocation,
`CareResponse` validation, Claude invocation, or orchestration log/trace verification
was possible. The failed stack and retained log group require a separately approved
recovery before another deployment attempt.

## Proposed temporary deployment policy and recovery

The Phase 3 strategy now separates the long-lived runtime role from a temporary,
broader CloudFormation deployment policy. The runtime role is unchanged: its Claude
Sonnet 4.6 inference-profile, ECR pull, runtime logging, tracing, and metrics permissions
remain exactly as reviewed. Only `CareCirclePhase3CdkExecutionPolicy` is proposed for
revision, and no live policy or AWS resource has been changed.

The CloudFormation registry schema for `AWS::BedrockAgentCore::Runtime` confirms that
one runtime resource handler can call runtime, endpoint, workload-identity,
service-linked-role, and `iam:PassRole` operations during create/update/delete. The
proposed policy therefore grants complete action families for the reviewed stack's
resource types rather than waiting for each handler action to fail separately.

The proposed deployment statements are:

```yaml
- Sid: ManageCareCircleEcrRepository
  Effect: Allow
  Action: ecr:*
  Resource: arn:${AWS::Partition}:ecr:${AWS::Region}:${AWS::AccountId}:repository/carecirclephase3/carecirclemcp
- Sid: CreateTaggedCareCircleKmsKey
  Effect: Allow
  Action: kms:CreateKey
  Resource: "*"
  Condition:
    StringEquals:
      aws:RequestTag/Project: CareCircle
      aws:RequestTag/Environment: Hackathon
- Sid: ManageTaggedCareCircleKmsKey
  Effect: Allow
  Action:
    - kms:CreateGrant
    - kms:DescribeKey
    - kms:DisableKey
    - kms:DisableKeyRotation
    - kms:EnableKey
    - kms:EnableKeyRotation
    - kms:GetKeyPolicy
    - kms:GetKeyRotationStatus
    - kms:ListResourceTags
    - kms:PutKeyPolicy
    - kms:ScheduleKeyDeletion
    - kms:TagResource
    - kms:UntagResource
    - kms:UpdateKeyDescription
  Resource: arn:${AWS::Partition}:kms:${AWS::Region}:${AWS::AccountId}:key/*
  Condition:
    StringEquals:
      aws:ResourceTag/Project: CareCircle
      aws:ResourceTag/Environment: Hackathon
- Sid: ManageCareCircleGeneratedRoles
  Effect: Allow
  Action: iam:*
  Resource: arn:${AWS::Partition}:iam::${AWS::AccountId}:role/AgentCore-CareCirclePhase-*
- Sid: PassCareCircleRuntimeRoleToAgentCore
  Effect: Allow
  Action: iam:PassRole
  Resource: arn:${AWS::Partition}:iam::${AWS::AccountId}:role/CareCirclePhase3AgentCoreRuntimeRole
  Condition:
    StringEquals:
      iam:PassedToService: bedrock-agentcore.amazonaws.com
- Sid: CreateAgentCoreServiceLinkedRole
  Effect: Allow
  Action: iam:CreateServiceLinkedRole
  Resource: arn:${AWS::Partition}:iam::${AWS::AccountId}:role/aws-service-role/bedrock-agentcore.amazonaws.com/*
  Condition:
    StringEquals:
      iam:AWSServiceName: bedrock-agentcore.amazonaws.com
- Sid: ManageCareCircleLambda
  Effect: Allow
  Action: lambda:*
  Resource: arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
- Sid: ManageCareCircleLambdaLogs
  Effect: Allow
  Action: logs:*
  Resource: arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-*
- Sid: ManageCareCircleCodeBuildProject
  Effect: Allow
  Action: codebuild:*
  Resource: arn:${AWS::Partition}:codebuild:${AWS::Region}:${AWS::AccountId}:project/AgentCore-CareCirclePhase3-default-container-builder
- Sid: ManageCareCircleRuntime
  Effect: Allow
  Action:
    - bedrock-agentcore:CreateAgentRuntime*
    - bedrock-agentcore:DeleteAgentRuntime*
    - bedrock-agentcore:GetAgentRuntime*
    - bedrock-agentcore:TagResource
    - bedrock-agentcore:UntagResource
    - bedrock-agentcore:ListTagsForResource
    - bedrock-agentcore:UpdateAgentRuntime*
  Resource: arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:runtime/*
- Sid: ListCareCircleRuntimeLifecycle
  Effect: Allow
  Action:
    - bedrock-agentcore:ListAgentRuntimeEndpoints
    - bedrock-agentcore:ListAgentRuntimes
  Resource: "*"
- Sid: ManageRuntimeWorkloadIdentity
  Effect: Allow
  Action:
    - bedrock-agentcore:CreateWorkloadIdentity
    - bedrock-agentcore:DeleteWorkloadIdentity
  Resource: arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:workload-identity-directory/default/workload-identity/*
```

The existing CDK asset-bucket read and bootstrap SSM read statements remain unchanged.
No Bedrock model permission is present in the deployment policy.

Permissions intentionally broader than the desired final policy are `ecr:*`, `iam:*`,
`lambda:*`, `logs:*`, and `codebuild:*` on their project-specific resources, plus the
AgentCore runtime lifecycle action wildcards and account-level runtime list calls.
`iam:PassRole` remains restricted to the exact runtime role and AgentCore service;
service-linked-role creation is restricted to AgentCore. KMS remains an explicit
CloudFormation-handler action set because `kms:*` cannot safely retain the tag
conditions across actions that do not support them.

The following handler-schema capabilities are deliberately excluded because the
synthesized stack does not use them: EC2 networking, VPC Lattice, VPC-mode network
interfaces, S3 code artifacts, capacity providers, and unrelated AgentCore services.
AdministratorAccess and unrelated application/data services are not included.

Validation of the proposed local template completed successfully:

- CloudFormation `validate-template`: passed.
- AgentCore `validate --json`: `success: true`.
- CDK TypeScript build: passed.
- IAM Access Analyzer `validate-policy`: zero findings.
- `git diff --check`: passed.

### Prepared recovery sequence — not executed

The read-only preparation audit reconfirmed the failed stack is `ROLLBACK_COMPLETE`.
The exact retained log group still exists with zero stored bytes and 731-day retention,
has no subscription filters, and its corresponding Lambda is absent. KMS key
`eb2e4c12-1c3f-464b-8e57-4fe0a4217b3e` remains `PendingDeletion` for
2026-10-18T11:19:41.442000-07:00.

1. Reconfirm the caller is the non-root `carecircle-admin` SSO role.
2. Reconfirm `AgentCore-CareCirclePhase3-default` is `ROLLBACK_COMPLETE` and inventory
   its resources.
3. Reconfirm the generated Lambda is absent; the retained log group is still exactly
   `/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YGey9PcNgIev`, has
   zero stored bytes, and has no subscription filter or destination.
4. After explicit approval, deploy only the proposed
   `CareCirclePhase3Prerequisites` policy revision and verify that the runtime role's
   inline policy document is unchanged.
5. Delete only `AgentCore-CareCirclePhase3-default` and wait for
   `stack-delete-complete`.
6. Delete only the retained zero-byte Lambda log group after reconfirming it has no
   active owner or subscription.
7. Verify the failed-attempt KMS key remains `PendingDeletion`; verify the prerequisite
   and bootstrap stacks remain healthy; audit for CareCircle Lambda, IAM, CodeBuild,
   ECR, AgentCore, Logs, and KMS orphans.
8. Stop and report recovery state before any deployment retry unless the next approval
   explicitly authorizes both recovery and retry.

### Post-success tightening plan

Record the successful deployment start/end timestamps and stack ID. Query CloudTrail
management events for that interval, then retain only events whose principal is the
`cdk-hnb659fds-cfn-exec-role-109837542034-us-east-1` CloudFormation session and whose
resources or request tags identify the CareCircle stack. Compare the observed action
set with this temporary policy, replace wildcard action families with the exercised
lifecycle actions plus documented update/delete requirements, validate with Access
Analyzer, and deploy the tightened policy as a new managed-policy version. Generated
Lambda and CodeBuild role activity will be reviewed separately and will not be used to
inflate the CloudFormation deployment role.

## 2026-09-18 temporary-policy update stopped before recovery

The approved sequence stopped at its first mutating step. Updating
`CareCirclePhase3Prerequisites` failed because the proposed template changed the
`Description` of the named `AWS::IAM::ManagedPolicy`. The CloudFormation registry
schema marks `/properties/Description` as create-only, so CloudFormation attempted to
replace `CareCirclePhase3CdkExecutionPolicy` while the existing policy with that fixed
name still existed. IAM rejected the replacement:

```text
A policy called CareCirclePhase3CdkExecutionPolicy already exists. Duplicate names are not allowed. (Service: Iam, Status Code: 409, Request ID: 6e926965-cecb-483f-b908-49430a66b3c1)
```

`CareCirclePhase3Prerequisites` rolled back successfully to
`UPDATE_ROLLBACK_COMPLETE`. Live managed-policy version `v5` remains the sole and
default version, so none of the proposed temporary permissions were applied. The
AgentCore runtime role's inline policy remains unchanged.

The authorized recovery and deployment sequence did not begin. The failed project
stack remains `ROLLBACK_COMPLETE`, and retained log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YGey9PcNgIev` remains
present with zero stored bytes. No stack or log group was deleted and no deployment
retry occurred.

The narrow correction would preserve the existing managed-policy description so
CloudFormation can update its policy document in place. That correction has not been
made because this was a new failure and requires review before another mutation.

## In-place policy update, recovery, and stopped deployment retry

Under explicit approval, the managed-policy description was restored exactly to its
live value:

```text
Permissions used by CloudFormation only for the CareCircle Phase 3 stack
```

CloudFormation validation, IAM Access Analyzer validation, CDK synthesis, and
`agentcore validate` all passed. `CareCirclePhase3Prerequisites` reached
`UPDATE_COMPLETE`; the managed policy retained ARN
`arn:aws:iam::109837542034:policy/CareCirclePhase3CdkExecutionPolicy` and its original
2026-09-18T17:18:27Z creation time, while the default policy version advanced in place
from `v5` to `v6`. The AgentCore runtime role document remained unchanged.

The previously failed project stack was then deleted and confirmed absent. Its retained
zero-byte log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-YGey9PcNgIev` was
reconfirmed orphaned with no subscription and deleted. KMS key
`eb2e4c12-1c3f-464b-8e57-4fe0a4217b3e` remained `PendingDeletion`. A clean audit found
no CareCircle project stack, ECR repository, CodeBuild project, generated role, helper
Lambda, Lambda log group, or AgentCore runtime before the retry. The prerequisite and
bootstrap stacks were healthy, and Claude Sonnet 4.6 was `ACTIVE`.

The approved retry began at 2026-09-18T18:43:15Z. The ARM64 image built and pushed as:

```text
109837542034.dkr.ecr.us-east-1.amazonaws.com/carecirclephase3/carecirclemcp:bf370837756c305009544fe69ff7e464a7ecc169d29ddffcb26592f629e29686
```

AgentCore Runtime creation failed at 2026-09-18T18:45:52.008Z. CloudTrail exposes the
underlying permission denial:

```text
bedrock-agentcore:TagResource on
arn:aws:bedrock-agentcore:us-east-1:109837542034:workload-identity-directory/default/workload-identity/*
```

The temporary policy allowed `CreateWorkloadIdentity` and `DeleteWorkloadIdentity` on
that workload-identity prefix, and allowed `TagResource` on `runtime/*`, but it did not
allow `TagResource` on the workload-identity resource. No policy correction was made.

Automatic rollback reached `ROLLBACK_COMPLETE`. It removed the ECR repository,
CodeBuild project, helper Lambda, generated roles/policies, and uncreated runtime
record. KMS key `566b6716-d270-4aea-b43d-3f26f8cb03c8` is `PendingDeletion`, scheduled
for 2026-10-18T11:48:22.147000-07:00. The zero-byte log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-fgxF3XS455tH` was
retained with 731-day retention. The failed stack remains `ROLLBACK_COMPLETE`.

Because the runtime was never created, remote MCP invocation, `CareResponse`
validation, Claude invocation evidence, orchestration logs, and successful-deployment
CloudTrail action analysis were not possible. The checked-in AgentCore execution-role
ARN was restored to the portable `000000000000` placeholder.

## Prepared workload-identity lifecycle correction — not applied

The proposed `ManageRuntimeWorkloadIdentity` statement now contains exactly:

```yaml
- Sid: ManageRuntimeWorkloadIdentity
  Effect: Allow
  Action:
    - bedrock-agentcore:CreateWorkloadIdentity
    - bedrock-agentcore:GetWorkloadIdentity
    - bedrock-agentcore:UpdateWorkloadIdentity
    - bedrock-agentcore:DeleteWorkloadIdentity
    - bedrock-agentcore:TagResource
    - bedrock-agentcore:UntagResource
    - bedrock-agentcore:ListTagsForResource
  Resource: !Sub arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:workload-identity-directory/default/workload-identity/*
```

No other deployment-policy statement or runtime-role permission changed. AWS's service
authorization reference confirms that workload identities use this ARN hierarchy and
support the read, update, and tagging actions. The `CreateWorkloadIdentity` API accepts
tags, and the AgentCore identity-tagging guide confirms workload identities support
tag-on-create and subsequent tagging.

The current CloudFormation registry schema and synthesized runtime were reviewed again.
The synthesis remains an MCP container runtime using public networking, the exact
CareCircle runtime role, and no authorizer, VPC configuration, capacity provider,
filesystem, or S3 code artifact. The current policy covers the applicable runtime and
endpoint handler families, runtime-role `iam:PassRole`, workload-identity lifecycle,
and tagging. VPC/EC2/VPC Lattice, capacity-provider, and S3 code permissions remain
inapplicable.

The official service-linked-role documentation identifies
`runtime-identity.bedrock-agentcore.amazonaws.com` as the service name for
`AWSServiceRoleForBedrockAgentCoreRuntimeIdentity`. The current temporary policy's
`CreateAgentCoreServiceLinkedRole` statement instead targets
`bedrock-agentcore.amazonaws.com`, the gateway service name. This is a latent policy
gap if the runtime-identity service-linked role must be created in another account or
after deletion. It is not a blocker in the current account: the exact
`AWSServiceRoleForBedrockAgentCoreRuntimeIdentity` role already exists, created on
2026-09-02T03:29:41Z. The statement was not changed because this review was authorized
only for the workload-identity lifecycle correction.

Validation results for the prepared local change:

- IAM Access Analyzer: zero findings.
- CloudFormation `validate-template`: passed.
- CDK synthesis: passed.
- `agentcore validate --json`: `success: true`.
- `git diff --check`: passed.

No additional AgentCore identity/control-plane gap is evident for the current account
and synthesized public-container runtime. The service-linked-role mismatch remains a
documented portability/role-recreation gap and should be explicitly accepted or
corrected before retry approval.

### Prepared recovery — not executed

The read-only audit reconfirmed:

- `AgentCore-CareCirclePhase3-default` is `ROLLBACK_COMPLETE`, stack ID
  `e1b20980-b390-11f1-b451-1237069f60b1`.
- Its Lambda is absent.
- Retained log group
  `/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-fgxF3XS455tH` exists
  with zero stored bytes, 731-day retention, and no subscription filters.
- KMS key `566b6716-d270-4aea-b43d-3f26f8cb03c8` remains `PendingDeletion`, scheduled
  for 2026-10-18T11:48:22.147000-07:00.
- `CareCirclePhase3Prerequisites` is `UPDATE_COMPLETE`; `CDKToolkit` is
  `CREATE_COMPLETE`.

The prepared recovery sequence is to apply only the approved prerequisite-policy
version, verify the runtime role is unchanged, delete only the failed project stack and
wait for `DELETE_COMPLETE`, reconfirm the retained log group is orphaned/zero-byte with
no subscriptions, delete only that log group, and audit the KMS/support/project state.
No part of this sequence was executed during preparation.

## 2026-09-18 approved v7 update, recovery, and stopped deployment retry

The exact approved runtime-identity service-linked-role permission was applied in
place to `CareCirclePhase3CdkExecutionPolicy`. `CareCirclePhase3Prerequisites` reached
`UPDATE_COMPLETE`, the same managed-policy ARN advanced to default version `v7`, and
`CareCirclePhase3AgentCoreRuntimeRole` was not changed. The live statement is:

```yaml
- Sid: CreateAgentCoreRuntimeIdentityServiceLinkedRole
  Effect: Allow
  Action: iam:CreateServiceLinkedRole
  Resource: arn:aws:iam::109837542034:role/aws-service-role/runtime-identity.bedrock-agentcore.amazonaws.com/AWSServiceRoleForBedrockAgentCoreRuntimeIdentity
  Condition:
    StringEquals:
      iam:AWSServiceName: runtime-identity.bedrock-agentcore.amazonaws.com
```

The previously failed stack was deleted, its confirmed orphaned zero-byte Lambda log
group was deleted, and the clean-state audit passed before retry. The retry began at
2026-09-18T19:03:27Z. The ARM64 build completed and pushed image digest
`sha256:bf370837756c305009544fe69ff7e464a7ecc169d29ddffcb26592f629e29686` to
`carecirclephase3/carecirclemcp`. Runtime creation then failed at
2026-09-18T19:06:04Z and automatic rollback reached `ROLLBACK_COMPLETE`.

CloudTrail records both the outer `CreateAgentRuntime` failure and the underlying
denied call. The actionable response is:

```text
bedrock-agentcore:CreateWorkloadIdentity on
arn:aws:bedrock-agentcore:us-east-1:109837542034:workload-identity-directory/default
because no identity-based policy allows the action
```

This is a resource-scope mismatch. The reviewed statement authorizes the lifecycle on
`workload-identity-directory/default/workload-identity/*`, but AgentCore evaluates
the create action against the parent directory resource
`workload-identity-directory/default`. IAM simulation confirms the child identity ARN
is allowed; it does not match the parent directory ARN used by the live create call.
No IAM statement was changed after this new failure and no further retry was made.

Rollback removed the ECR repository, CodeBuild project, helper Lambda, generated IAM
roles and policies, and the uncreated runtime record. It retained the zero-byte,
731-day log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-WK62DwbxwhOE` with no
subscription filters. KMS key `53ed9a8c-dcfc-4e4c-bdf2-66e69d764836` is
`PendingDeletion`, scheduled for 2026-10-18T12:08:31.012000-07:00.
`CareCirclePhase3Prerequisites` remains `UPDATE_COMPLETE`, `CDKToolkit` remains
`CREATE_COMPLETE`, and the checked-in AgentCore role ARN has been restored to the
portable `000000000000` placeholder.

The next policy or recovery mutation requires separate approval. A successful runtime,
remote MCP result, CareResponse validation, orchestration logs, and successful-run
CloudTrail inventory are not available from this stopped retry.

## Prepared parent-directory workload-identity correction — not applied

The proposed temporary deployment policy now separates workload identity creation from
child-resource lifecycle operations. This matches the parent directory ARN observed in
the 2026-09-18 CloudTrail denial while preserving the narrower identity ARN for all
post-creation actions:

```yaml
- Sid: CreateCareCircleWorkloadIdentity
  Effect: Allow
  Action:
    - bedrock-agentcore:CreateWorkloadIdentity
    - bedrock-agentcore:ListWorkloadIdentities
  Resource: !Sub arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:workload-identity-directory/default
- Sid: ManageRuntimeWorkloadIdentity
  Effect: Allow
  Action:
    - bedrock-agentcore:GetWorkloadIdentity
    - bedrock-agentcore:UpdateWorkloadIdentity
    - bedrock-agentcore:DeleteWorkloadIdentity
    - bedrock-agentcore:TagResource
    - bedrock-agentcore:UntagResource
    - bedrock-agentcore:ListTagsForResource
  Resource: !Sub arn:${AWS::Partition}:bedrock-agentcore:${AWS::Region}:${AWS::AccountId}:workload-identity-directory/default/workload-identity/*
```

The already approved `CreateAgentCoreRuntimeIdentityServiceLinkedRole` statement for
`runtime-identity.bedrock-agentcore.amazonaws.com` is unchanged. The AgentCore runtime
role and Claude Sonnet 4.6 permissions are unchanged. The proposal adds no
`bedrock-agentcore:*` action and no `Resource: "*"` statement.

Validation results:

- IAM Access Analyzer `validate-policy`: zero findings.
- CloudFormation `validate-template`: passed.
- TypeScript build and CDK synthesis: passed; only the known non-blocking `pyenv`
  rehash warning and CDK feature-flag notice were emitted.
- `agentcore validate --json`: `success: true`.
- `git diff --check`: passed.

### Prepared recovery — not executed

The read-only inventory reconfirmed:

- `AgentCore-CareCirclePhase3-default` is `ROLLBACK_COMPLETE`, stack ID
  `b1f2f490-b393-11f1-8d1b-0efb6c8a3409`.
- Helper Lambda
  `AgentCore-CareCirclePhase-ApplicationAgentCareCirc-WK62DwbxwhOE` is absent.
- Retained log group
  `/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-WK62DwbxwhOE` has
  zero stored bytes, 731-day retention, and no subscription filters.
- KMS key `53ed9a8c-dcfc-4e4c-bdf2-66e69d764836` is `PendingDeletion`, scheduled for
  2026-10-18T12:08:31.012000-07:00.
- `CareCirclePhase3Prerequisites` is `UPDATE_COMPLETE`; `CDKToolkit` is
  `CREATE_COMPLETE`.

After separate approval, the prepared sequence is:

1. Apply only the reviewed `CareCirclePhase3Prerequisites` policy-document update and
   verify in-place policy versioning, unchanged runtime role, and `UPDATE_COMPLETE`.
2. Reconfirm the project stack is `ROLLBACK_COMPLETE` and inventory its resources.
3. Delete only `AgentCore-CareCirclePhase3-default` and wait for CloudFormation to
   report deletion complete.
4. Reconfirm the exact retained log group is orphaned, zero-byte, has no subscriptions,
   and its Lambda remains absent; then delete only that log group.
5. Verify the KMS key remains `PendingDeletion`, prerequisites and bootstrap remain
   healthy, and no active project resources remain.

No prerequisite update, stack deletion, log deletion, or deployment retry was executed
during this preparation.

## 2026-09-18 v8 application, recovery, and stopped retry

The reviewed parent/child workload-identity split was applied in place. The
`CareCirclePhase3CdkExecutionPolicy` ARN, policy ID, and creation date remained the
same, and its default version advanced from `v7` to `v8`.
`CareCirclePhase3Prerequisites` reached `UPDATE_COMPLETE`. Comparison of the runtime
role ARN, role ID, trust policy, and inline `CareCirclePhase3Runtime` policy before and
after the update found no change. The approved runtime-identity service-linked-role
statement also remains present and unchanged.

The prior `ROLLBACK_COMPLETE` project stack was deleted. Its retained log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-WK62DwbxwhOE` was
reconfirmed as orphaned, zero-byte, and without subscriptions, then deleted. KMS key
`53ed9a8c-dcfc-4e4c-bdf2-66e69d764836` remained `PendingDeletion`. A clean-state audit
found no project Lambda, Lambda log group, CodeBuild project, ECR repository, generated
build IAM resource, or AgentCore runtime before retry.

The retry began at 2026-09-18T19:22:07Z. The ARM64 build completed and pushed image
digest `sha256:bf370837756c305009544fe69ff7e464a7ecc169d29ddffcb26592f629e29686`.
Runtime creation failed at 2026-09-18T19:24:55Z. CloudTrail records the exact nested
denial:

```text
bedrock-agentcore:CreateWorkloadIdentity on
arn:aws:bedrock-agentcore:us-east-1:109837542034:workload-identity-directory/default/workload-identity/*
because no identity-based policy allows the action
```

The previous attempt proved that AgentCore evaluates the create call against the
parent directory ARN. This attempt proves the same operation is also evaluated against
the child workload-identity ARN pattern. The approved v8 split authorizes
`CreateWorkloadIdentity` only on the parent, so the second resource check did not
match. No IAM correction or retry followed this new denial.

Automatic rollback reached `ROLLBACK_COMPLETE` and removed the ECR repository,
CodeBuild project, helper Lambda, generated IAM resources, and incomplete runtime. It
retained zero-byte log group
`/aws/lambda/AgentCore-CareCirclePhase-ApplicationAgentCareCirc-y57NSpgKEVvX` with
731-day retention and no subscriptions. KMS key
`5b8b02f2-3aba-4604-ba4b-ce4b7fd4859b` is `PendingDeletion`, scheduled for
2026-10-18T12:27:40.258000-07:00. Prerequisites remain `UPDATE_COMPLETE`, bootstrap
remains `CREATE_COMPLETE`, and no AgentCore runtime exists. The portable
`000000000000` execution-role placeholder was restored locally.

Because deployment did not succeed, no remote MCP invocation, CareResponse validation,
or successful-deployment CloudTrail action inventory was produced. Any change that
authorizes `CreateWorkloadIdentity` on both evaluated resources requires separate
review and approval.

## Final Phase 3 deployment — successful

The final deployment strategy temporarily broadened only the CDK/CloudFormation
execution policy's AgentCore control-plane statement:

```yaml
- Sid: ManageAgentCoreDeploymentLifecycle
  Effect: Allow
  Action: bedrock-agentcore:*
  Resource: "*"
```

This exception is confined to `CareCirclePhase3CdkExecutionPolicy`. The policy was
updated in place from `v8` to `v9`; its ARN, policy ID, creation date, and immutable
description remained unchanged. The runtime role's ARN, role ID, trust policy, and
inline `CareCirclePhase3Runtime` policy were identical before and after the update.
The runtime role retains only reviewed runtime access, including Claude Sonnet 4.6
inference-profile/model invocation, ECR image pull, and runtime logging/telemetry.

Before applying v9, CloudFormation validation, CDK synthesis, AgentCore validation,
and IAM Access Analyzer all passed. The caller was the non-root `carecircle-admin` SSO
role, and inference profile `us.anthropic.claude-sonnet-4-6` was `ACTIVE`.

The prior failed stack and retained zero-byte log group were deleted after the required
ownership, Lambda-absence, byte-count, and subscription checks. KMS key
`5b8b02f2-3aba-4604-ba4b-ce4b7fd4859b` remained `PendingDeletion`. A clean audit found
no active project deployment resources before the final retry.

The final deployment ran from 2026-09-18T20:07:45Z and reached `CREATE_COMPLETE` at
2026-09-18T20:10:46Z. Stack ID:

```text
arn:aws:cloudformation:us-east-1:109837542034:stack/AgentCore-CareCirclePhase3-default/bbf60a50-b39c-11f1-84ee-0affe364b801
```

Created resources:

- ECR repository `carecirclephase3/carecirclemcp`.
- KMS key `5ad59c95-bcda-43f1-9d1e-2c26c3f896f0` for repository encryption.
- Helper Lambda `AgentCore-CareCirclePhase-ApplicationAgentCareCirc-Pe4ZctDgbC7a`
  and log group with the corresponding `/aws/lambda/` name.
- Helper role
  `AgentCore-CareCirclePhase-ApplicationAgentCareCircl-2ic4vzOlU2oE` and inline
  policy `Agent-Appli-C1qYinLR8NIB`.
- CodeBuild project `AgentCore-CareCirclePhase3-default-container-builder`.
- CodeBuild role
  `AgentCore-CareCirclePhase-ContainerBuildProjectCont-jT0QbO1p0IQE` and inline
  policy `Agent-Conta-DHc7KH6nFuok`.
- Container-build custom resource whose physical ID is the ECR image URI/tag.
- AgentCore runtime `CareCirclePhase3_CareCircleMcp-XjLaBWDGYa`, version 1.
- AgentCore workload identity under the default workload-identity directory.
- AgentCore `DEFAULT` endpoint, version 1.
- CDK metadata record.

The ECR image tag is
`bf370837756c305009544fe69ff7e464a7ecc169d29ddffcb26592f629e29686`; its immutable
registry digest is
`sha256:739005c311cacadd2362e96b187d1e21fec57b964e580303e215a99d17caf54a`.
Both the runtime and endpoint reported `READY`.

### Remote verification

The IAM-authenticated MCP client initialized protocol `2025-11-25`, called
`coordinate_care_request` with session `phase3-remote-demo`, and validated the returned
`structuredContent` as `CareResponse`:

- incident ID: `356c140d-3373-4971-a7fb-fc5ec1855d9a`
- risk level: `high`
- evidence count: 4
- proposed action count: 1
- total client latency: 5114.29 ms

Privacy-safe runtime logs for that exact session and incident show
`mcp_tool_invoked`, successful `triage`, successful `medication`, and
`supervisor_completed` with selected specialists `["triage", "medication"]`, policy
outcome `caregiver_review`, and outcome `success`. The application log contains no
utterance, prompt, medication record, credential, or exception text.

The runtime environment identifies model
`us.anthropic.claude-sonnet-4-6`; the unchanged runtime role permits only that US
inference profile and its backing Sonnet 4.6 model resources. CloudWatch namespace
`AWS/Bedrock` recorded one `Invocations` datapoint for model dimension
`us.anthropic.claude-sonnet-4-6` in the 20:12Z remote-request minute. Together with the
3.237-second successful triage span in the runtime log, this confirms the remote
request invoked Claude Sonnet 4.6 before deterministic policy evaluation and medication
fact retrieval.

The successful deployment's CloudTrail action inventory is recorded in
`docs/phase3-deployment-actions.md`. The broad temporary policy remains in place for a
separate tightening task, as requested. The account-specific runtime-role ARN was
restored to the committed `000000000000` placeholder after deployment. Successful
Phase 3 resources were not cleaned up, and no Phase 4 resource was created.

## Full-build extension checkpoint — 2026-09-20

The complete hackathon expansion is reviewed separately in
`infra/full-build-review.md`: three CareCircle DynamoDB tables, an SNS topic and
synthetic Lambda inbox subscription, a one-shot follow-up Lambda and Scheduler
role, and in-place runtime-role/AgentCore updates. The Phase 3 temporary CDK
deployment policy is unchanged. The new CloudFormation template validates, but
automatic approval review rejected its deployment because earlier direct Phase 3
instructions prohibited those services and the new build request was supplied in
an attachment. No new AWS resources were created. The existing Phase 3 stack remains
`CREATE_COMPLETE` and runtime remains `READY`.

## Approved full-build deployment — 2026-09-20

The subsequent direct approval covered `CareCircleFullBuild`, the in-place
`CareCirclePhase3Prerequisites` runtime-role additions, and an in-place AgentCore
runtime update. The caller was the non-root `carecircle-admin` SSO role. Current
CloudFormation status: `CareCircleFullBuild`, `CareCirclePhase3Prerequisites`,
and `AgentCore-CareCirclePhase3-default` are `UPDATE_COMPLETE`. The original
AgentCore runtime ARN and `DEFAULT` endpoint are `READY`. The runtime role kept
RoleId `AROARTEWT4KJNLOHBDG64`; the temporary CDK execution managed policy kept
PolicyId `ANPARTEWT4KJJMZYTNQX3` and version `v9`.

`CareCircleFullBuild` created exactly these CloudFormation resources:

| Type | Physical resource |
| --- | --- |
| DynamoDB table | `CareCircleCareProfiles` |
| DynamoDB table | `CareCircleCareEvents` |
| DynamoDB table | `CareCircleActionLedger` |
| SNS topic | `arn:aws:sns:us-east-1:109837542034:CareCircleCaregiverAlerts` |
| SNS subscription | `arn:aws:sns:us-east-1:109837542034:CareCircleCaregiverAlerts:6ab0ee1e-48c9-491e-b879-95f1dea40e28` |
| Lambda function | `CareCircleFollowUp` |
| Lambda log group | `/aws/lambda/CareCircleFollowUp` |
| Lambda execution role | `CareCircleFollowUpLambdaRole` |
| Scheduler execution role | `CareCircleFollowUpSchedulerRole` |
| Lambda permission | `CareCircleFullBuild-CaregiverAlertInvokePermission-nayv2xNBceND` |

Two approved demo actions also created `carecircle-<incident-id>` EventBridge
Scheduler one-shot schedules with `ActionAfterCompletion: DELETE`, outside the
stack. They targeted only `CareCircleFollowUp`.

The AgentCore update changed the container-build custom resource and runtime
environment variables, without replacing the Runtime or Endpoint. The existing
ECR repository received immutable digest
`sha256:2691887befb919779e7bb37c3e8e1379c78fdde4ad16278c05aead0606cd971f`.
No new AgentCore Runtime, ECR repository, KMS key, CodeBuild project, or temporary
deployment-policy version was created for this update.

The only post-deployment correction changed the Scheduler execution-role trust
`aws:SourceArn` from a schedule-name pattern to the exact default schedule-group
ARN, as required by [AWS documentation](https://docs.aws.amazon.com/scheduler/latest/UserGuide/cross-service-confused-deputy-prevention.html).
The principal, SourceAccount, and invoke-only policy stayed fixed. The first
approved SNS publish succeeded before Scheduler failed; an idempotent retry
created its schedule without a duplicate publish. The complete remote test then
passed, including Lambda follow-up and persistent backup action. See
`docs/full-build-completion.md` for identifiers, latency, logs, and model metrics.

The broader `bedrock-agentcore:*` deployment permission remains in the temporary
Phase 3 policy for a separate tightening task. This deployment did not modify it
or any unrelated AWS resource. Successful stacks were not cleaned up.
