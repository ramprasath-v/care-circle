# CareCircle AgentCore infrastructure

The current AgentCore CLI (`0.30.0`) generated the CDK-backed project under
`agentcore/CareCirclePhase3`. Its source of truth is
`agentcore/CareCirclePhase3/agentcore/agentcore.json`; generated CDK code is not
edited manually.

The project contains one BYO container runtime:

- name: `CareCircleMcp`
- protocol: MCP
- inbound authorization: AWS IAM
- network mode: public
- application path: `0.0.0.0:8000/mcp`
- idle timeout: 300 seconds
- maximum lifetime: 900 seconds
- OpenTelemetry instrumentation: enabled
- selected model: the `us.anthropic.claude-sonnet-4-6` US inference profile,
  invoked from `us-east-1`

The runtime uses a pre-created least-privilege role from
`iam/phase3-prerequisites.yaml`. The checked-in `executionRoleArn` contains the
non-account placeholder `000000000000`; replace that value only in the local
deployment copy after the prerequisite stack returns `RuntimeRoleArn`. This
prevents the AgentCore CLI from silently synthesizing its broader development
role, which permits every Bedrock foundation model.

The same prerequisite stack creates
`CareCirclePhase3CdkExecutionPolicy`. Pass its ARN to CDK bootstrap so the
bootstrap CloudFormation role does not receive `AdministratorAccess`.

From `infra/agentcore/CareCirclePhase3`:

```bash
agentcore validate
agentcore deploy --dry-run --json
agentcore deploy --diff
agentcore deploy --verbose
agentcore status --json
```

Do not run the final deploy command until the resource and cost review has been
approved. The deployment caller should be a named administrative/deployment role,
not the AWS account root principal.

The first deployment also needs the project-owned minimal CDK bootstrap template at
`../cdk-bootstrap.yaml`. Bootstrap must use the `CdkExecutionPolicyArn` output from
`iam/phase3-prerequisites.yaml`. The template creates only file-asset publishing
resources and omits the standard administrator, account-wide lookup, and container
publishing roles. The checked-in runtime-role ARN is a deliberate `000000000000`
placeholder and must be replaced only in the local deployment copy with the
prerequisite stack's `RuntimeRoleArn` output.
