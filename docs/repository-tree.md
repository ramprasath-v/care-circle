# CareCircle repository tree

Source and review artifacts; generated dependencies and CDK output omitted.

```text
CareCircle/
├── docs/
│   ├── friction-log.md
│   ├── full-build-completion.md
│   ├── full-build-inventory.md
│   ├── phase3-deployment-actions.md
│   └── repository-tree.md
├── infra/
│   ├── agentcore/
│   │   └── CareCirclePhase3/
│   │       ├── agentcore/
│   │       │   ├── cdk/
│   │       │   │   ├── bin/
│   │       │   │   │   └── cdk.ts
│   │       │   │   ├── lib/
│   │       │   │   │   └── cdk-stack.ts
│   │       │   │   ├── test/
│   │       │   │   │   └── cdk.test.ts
│   │       │   │   ├── cdk.json
│   │       │   │   ├── jest.config.js
│   │       │   │   ├── package-lock.json
│   │       │   │   ├── package.json
│   │       │   │   ├── README.md
│   │       │   │   └── tsconfig.json
│   │       │   ├── agentcore.json
│   │       │   └── aws-targets.example.json
│   │       ├── AGENTS.md
│   │       └── README.md
│   ├── iam/
│   │   └── phase3-prerequisites.yaml
│   ├── cdk-bootstrap.yaml
│   ├── full-build-review.md
│   ├── full-build.yaml
│   ├── local-overlay.Dockerfile
│   ├── README.md
│   └── resource-review.md
├── scripts/
│   ├── seed_demo.py
│   ├── test_client.py
│   ├── test_full_remote.py
│   ├── test_live_bedrock.py
│   └── test_remote_agentcore.py
├── src/
│   └── carecircle/
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── medication.py
│       │   └── triage.py
│       ├── policy/
│       │   ├── __init__.py
│       │   └── red_flag_rules.py
│       ├── providers/
│       │   ├── __init__.py
│       │   ├── aws_actions.py
│       │   ├── medication.py
│       │   └── ring.py
│       ├── web_assets/
│       │   └── index.html
│       ├── __init__.py
│       ├── app.py
│       ├── config.py
│       ├── full_supervisor.py
│       ├── internal_tools.py
│       ├── prompts.py
│       ├── remote.py
│       ├── schemas.py
│       ├── state.py
│       ├── strands_orchestration.py
│       ├── supervisor.py
│       ├── web.py
│       └── workflow.py
├── tests/
│   ├── conftest.py
│   ├── test_aws_adapters.py
│   ├── test_full_build.py
│   ├── test_full_mcp.py
│   ├── test_inline_lambda.py
│   ├── test_mcp_contract.py
│   ├── test_medication.py
│   ├── test_red_flag_rules.py
│   ├── test_schemas.py
│   ├── test_supervisor.py
│   ├── test_triage.py
│   └── test_web.py
├── .dockerignore
├── .env.example
├── .gitignore
├── Dockerfile
├── pyproject.toml
├── README.md
└── uv.lock
```
