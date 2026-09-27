# CareCircle Phase 3 deployment action inventory

This inventory covers the successful deployment window from
2026-09-18T20:07:45Z through 2026-09-18T20:11:30Z in `us-east-1`. Events were selected
from CloudTrail Event History for the CloudFormation execution-role session and the
CareCircle helper Lambda, CodeBuild, and runtime-role sessions created by the stack.
Repeated polling, layer transfer, decrypt, and log-stream calls are listed once.

## AgentCore

- `CreateAgentRuntime`
- `CreateWorkloadIdentity`
- `GetAgentRuntime`
- `ListAgentRuntimeEndpoints`
- `ListTagsForResource`

The successful deployment used temporary deployment-policy statement
`ManageAgentCoreDeploymentLifecycle`, which allows `bedrock-agentcore:*` on `*` only
for the CDK/CloudFormation execution role. Earlier resource-scoped policies failed
because `CreateWorkloadIdentity` was evaluated against both its directory and child
identity resource forms. The CareCircle runtime role was not broadened.

## IAM

- `AttachRolePolicy`
- `CreateRole`
- `GetRole`
- `GetRolePolicy`
- `ListAttachedRolePolicies`
- `ListRolePolicies`
- `PutRolePolicy`

CloudFormation also made non-blocking discovery probes for `GetAccountSummary`,
`ListPoliciesGrantingServiceAccess`, `ListAttachedRolePolicies`, and
`ListRolePolicies` that returned `AccessDenied`. The stack still reached
`CREATE_COMPLETE`; no permission was added for these optional probes.

## Lambda

- `CreateFunction20150331`
- `GetFunction20150331v2`
- `GetFunctionCodeSigningConfig`
- `GetFunctionRecursionConfig`
- `GetRuntimeManagementConfig`

`GetAccountSettings20160819` was attempted as a non-blocking discovery probe and
returned `AccessDenied`.

## CloudWatch Logs

- `CreateLogGroup`
- `CreateLogStream`
- `PutResourcePolicy`
- `PutRetentionPolicy`

`DescribeLogGroups` probes from the CloudFormation execution role returned
`AccessDenied` and did not block deployment. Log streams were also created by the
helper Lambda, CodeBuild role, and runtime role.

## CodeBuild

- `BatchGetBuilds`
- `BatchGetProjects`
- `CreateProject`
- `StartBuild`

## ECR

- `BatchCheckLayerAvailability`
- `BatchGetImage`
- `CompleteLayerUpload`
- `CreateRepository`
- `DescribeImages`
- `DescribeRepositories`
- `GetAuthorizationToken`
- `GetDownloadUrlForLayer`
- `GetLifecyclePolicy`
- `GetRepositoryPolicy`
- `InitiateLayerUpload`
- `ListTagsForResource`
- `PutImage`
- `PutLifecyclePolicy`
- `UploadLayerPart`

Initial `DescribeRepositories` and `GetRepositoryPolicy` calls returned expected
not-found results before repository and policy creation. ECR calls came from
CloudFormation, CodeBuild image publication, and AgentCore runtime image pulls.

## KMS

- `CreateGrant`
- `CreateKey`
- `Decrypt`
- `DescribeKey`
- `EnableKeyRotation`
- `GenerateDataKey`
- `GetKeyPolicy`
- `GetKeyRotationStatus`
- `ListResourceTags`

## S3

- `GetBucketAcl`
- `GetBucketLocation`

CloudTrail Event History does not include S3 object-level data events unless they are
configured on a trail. The completed CodeBuild asset download and build provide the
deployment result for the existing CDK asset-read path.

## SSM

- `GetParameters`

This read targeted the existing CDK bootstrap version parameter.

## Result

`AgentCore-CareCirclePhase3-default` reached `CREATE_COMPLETE`. No successful
deployment event in the reviewed window required DynamoDB, SNS, EventBridge, API
Gateway, EC2/VPC, or another application/data service. This document records observed
actions only; the temporary deployment policy is intentionally left unchanged for a
separate tightening task.
