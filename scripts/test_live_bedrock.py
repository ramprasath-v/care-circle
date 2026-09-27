"""Run one explicit, synthetic Bedrock integration check outside pytest."""
import asyncio
from time import perf_counter

from carecircle.config import Settings
from carecircle.schemas import CareRequest, TriageResult
from carecircle.supervisor import build_specialists


async def main() -> int:
    settings = Settings()
    print(f"model_id={settings.bedrock_model_id}")
    print(f"region={settings.aws_region}")
    started = perf_counter()
    try:
        triage, _ = build_specialists(settings)
        result = await triage.assess(CareRequest(
            household_id="demo-household",
            actor_role="caregiver",
            utterance="Dad says he may have missed his morning medication and seems confused.",
            session_id="live-bedrock-check",
        ))
        validated = TriageResult.model_validate(result)
    except Exception as exc:
        latency_ms = round((perf_counter() - started) * 1000, 2)
        print("invocation=failure")
        print(f"latency_ms={latency_ms}")
        print(f"failure_type={type(exc).__name__}")
        return 1

    latency_ms = round((perf_counter() - started) * 1000, 2)
    print("invocation=success")
    print(f"latency_ms={latency_ms}")
    print(f"result_summary={validated.recommended_next_step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
