"""Local voice-first demo; AWS calls and credentials stay on the server."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import re
from pathlib import Path
from time import monotonic, time
from uuid import uuid4

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from carecircle.live_progress import CloudWatchProgressSource
from carecircle.internal_tools import INTERNAL_TOOL_OWNERS
from carecircle.remote import RemoteCareCircle
from carecircle.speech import AmazonPollyProvider, AmazonTranscribeProvider, SpeechToTextProvider, TextToSpeechProvider
from carecircle.voice_intent import approval_decision


INDEX = Path(__file__).resolve().parent / "web_assets" / "index.html"
SCRIPT = INDEX.with_name("app.js")
PUBLIC_TOOLS = {"coordinate_care_request", "get_household_briefing", "confirm_action", "get_incident_status"}
TRACE_TOOL_ALIASES = {
    "refill_draft": "prepare_refill_request",
    "ride_draft": "prepare_ride_request",
    "supply_draft": "prepare_supply_request",
}
logger = logging.getLogger(__name__)


def create_web_app(remote: RemoteCareCircle | None = None, *,
                   stt: SpeechToTextProvider | None = None,
                   tts: TextToSpeechProvider | None = None,
                   progress_source: CloudWatchProgressSource | None = None) -> Starlette:
    region = os.getenv("AWS_REGION", "us-east-1")
    # A named profile is used locally when explicitly configured; hosted workloads
    # use the standard container credential chain supplied by their IAM role.
    profile = os.getenv("AWS_PROFILE")
    backend = remote or RemoteCareCircle(os.environ["AGENT_RUNTIME_ARN"], profile, region)
    speech_to_text = stt or AmazonTranscribeProvider(region, profile)
    jobs: dict[str, asyncio.Queue] = {}

    async def index(_):
        return FileResponse(INDEX, headers={"Cache-Control": "no-store"})

    async def script(_):
        return FileResponse(SCRIPT, media_type="text/javascript", headers={"Cache-Control": "no-store"})

    async def api(request):
        """Keep the existing direct proxy contract for older clients and tests."""
        body = await request.json()
        operation, arguments = body.get("operation"), body.get("arguments", {})
        if operation not in PUBLIC_TOOLS or not isinstance(arguments, dict):
            return JSONResponse({"error": "InvalidOperationOrArguments"}, status_code=400)
        try:
            return JSONResponse(await asyncio.to_thread(backend.call, operation, arguments))
        except Exception as exc:
            return JSONResponse({"error": type(exc).__name__}, status_code=502)

    async def transcribe(request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/octet-stream":
            return JSONResponse({"error": "ExpectedPcmAudio"}, status_code=415)
        if int(request.headers.get("content-length", "0")) > 640000:
            return JSONResponse({"error": "AudioTooLong"}, status_code=413)
        audio = await request.body()
        if len(audio) > 640000:
            return JSONResponse({"error": "AudioTooLong"}, status_code=413)
        try:
            value = await speech_to_text.transcribe(audio)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except Exception as exc:
            logger.exception("Amazon Transcribe request failed: %s", exc)
            return JSONResponse({"error": "TranscriptionUnavailable"}, status_code=502)
        return JSONResponse({"transcript": value.text, "latency_ms": value.latency_ms,
                             "provider": value.provider, "sample_rate_hz": value.sample_rate_hz})

    async def speak(request):
        body = await request.json()
        text = body.get("text")
        if not isinstance(text, str) or not text or len(text) > 1500:
            return JSONResponse({"error": "InvalidSpeechText"}, status_code=400)
        try:
            provider = tts or AmazonPollyProvider(region, profile)
            value = await asyncio.to_thread(provider.synthesize, text)
        except Exception:
            return JSONResponse({"error": "SpeechUnavailable"}, status_code=502)
        return Response(value.content, media_type=value.content_type,
                        headers={"Cache-Control": "no-store", "X-CareCircle-Voice": value.voice,
                                 "X-CareCircle-Latency-Ms": str(value.latency_ms)})

    async def voice_intent(request):
        body = await request.json()
        transcript, count = body.get("transcript"), body.get("pending_count")
        if not isinstance(transcript, str) or not isinstance(count, int) or count < 0:
            return JSONResponse({"error": "InvalidVoiceIntent"}, status_code=400)
        return JSONResponse({"decision": approval_decision(transcript, count)})

    async def start_job(request):
        request_received_at = monotonic()
        body = await request.json()
        operation, arguments = body.get("operation"), body.get("arguments", {})
        if operation not in PUBLIC_TOOLS or not isinstance(arguments, dict):
            return JSONResponse({"error": "InvalidOperationOrArguments"}, status_code=400)
        requested_session = arguments.get("session_id")
        session_id = (requested_session if isinstance(requested_session, str)
                      and re.fullmatch(r"voice-[A-Za-z0-9-]{1,100}", requested_session)
                      else f"voice-{uuid4().hex}")
        arguments = {**arguments, "session_id": session_id}
        job_id = uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        jobs[job_id] = queue
        started_ms = int(time() * 1000)

        async def run():
            await queue.put({"type": "progress", "trace_id": session_id, "component": "AgentCore / MCP",
                             "operation": operation, "status": "RUNNING", "message": "Connecting to CareCircle",
                             "timestamp": datetime.now(timezone.utc).isoformat()})
            invocation_started_at = monotonic()
            call = asyncio.create_task(asyncio.to_thread(backend.call, operation, arguments))
            source = progress_source
            seen: set[str] = set()
            observed_records: list[dict] = []
            after_done = 0
            result_sent = False
            result_sent_at = None
            agentcore_finished_at = None
            trace_error = False
            required_progress_seen = operation in {"get_incident_status", "confirm_action"}
            observed_complete_steps: set[tuple[str, str]] = set()
            briefing_components: set[str] = set()
            briefing_trace_deadline = monotonic() + 45
            while True:
                try:
                    if source is None:
                        source = CloudWatchProgressSource(backend.runtime_arn, region, profile)
                    records = await asyncio.to_thread(source.fetch, session_id, started_ms)
                    for record in records:
                        if record["event_id"] in seen:
                            continue
                        seen.add(record["event_id"])
                        observed_records.append(record)
                        if record.get("status") == "COMPLETE":
                            observed_complete_steps.add((record.get("component", ""), record.get("operation", "")))
                        if record["event"] == "mcp_tool_invoked":
                            continue
                        if (record.get("status") == "COMPLETE" and
                            ((operation == "coordinate_care_request" and record.get("component") == "CareCircle Supervisor" and record.get("operation") == "coordinate") or
                             (operation == "confirm_action" and record.get("operation") == "confirm_action"))):
                            required_progress_seen = True
                        if record.get("status") == "COMPLETE" and record.get("kind") == "tool" and record.get("component") in {
                            "Medication Agent", "Home Safety Agent", "Care Coordinator Agent", "Logistics & Routine Agent"
                        }:
                            briefing_components.add(record["component"])
                        await queue.put({"type": "progress", "trace_id": session_id, **{
                            key: value for key, value in record.items() if key not in {"event_id", "event", "session_id"}
                        }})
                except Exception:
                    if not trace_error:
                        await queue.put({"type": "progress", "trace_id": session_id,
                                         "component": "Live trace", "operation": "read_progress",
                                         "status": "FAILED", "message": "Live progress is unavailable; the care request is still running."})
                        trace_error = True
                if call.done():
                    if agentcore_finished_at is None:
                        agentcore_finished_at = monotonic()
                    wait_for_briefing_trace = (operation == "get_household_briefing" and
                                               len(briefing_components) < 4 and not trace_error and
                                               call.exception() is None and monotonic() < briefing_trace_deadline)
                    if not result_sent and not wait_for_briefing_trace:
                        try:
                            result = await call
                        except Exception as exc:
                            await queue.put({"type": "error", "error": type(exc).__name__})
                        else:
                            if operation == "coordinate_care_request" and isinstance(result, dict):
                                trace = result.get("trace", [])
                                for step in trace:
                                    operation_name = TRACE_TOOL_ALIASES.get(step.get("operation"), step.get("operation", ""))
                                    key = (step.get("component", ""), operation_name)
                                    if not step.get("success") or key in observed_complete_steps:
                                        continue
                                    await queue.put({
                                        "type": "progress", "trace_id": session_id,
                                        "component": key[0], "operation": key[1], "status": "COMPLETE",
                                        "latency_ms": step.get("latency_ms"),
                                        "kind": "tool" if key[1] in INTERNAL_TOOL_OWNERS else "agent",
                                        "source": "authoritative_response_trace",
                                    })
                                    observed_complete_steps.add(key)
                                required_progress_seen = bool(trace)
                            if (operation == "confirm_action" and isinstance(result, dict) and
                                result.get("provider_result", {}).get("provider") == "sns"):
                                for operation_name in ("send_approved_alert", "schedule_follow_up_check"):
                                    key = ("Care Coordinator Agent", operation_name)
                                    if key in observed_complete_steps:
                                        continue
                                    await queue.put({
                                        "type": "progress", "trace_id": session_id,
                                        "component": key[0], "operation": key[1], "status": "COMPLETE",
                                        "kind": "tool", "source": "authoritative_confirmation_result",
                                    })
                                    observed_complete_steps.add(key)
                            await queue.put({"type": "result", "operation": operation, "value": result,
                                             "trace_id": session_id})
                        result_sent = True
                        result_sent_at = monotonic()
                    if result_sent:
                        after_done += 1
                    if result_sent and (operation == "get_household_briefing" or required_progress_seen or
                                        trace_error or after_done >= 13):
                        break
                await asyncio.sleep(0.8)
            completed_at = monotonic()
            complete_records = [x for x in observed_records if x.get("status") == "COMPLETE"]
            timing = {
                "operation": operation,
                "app_runner_receive_to_mcp_start_ms": round((invocation_started_at-request_received_at)*1000, 2),
                "agentcore_mcp_ms": round(((agentcore_finished_at or completed_at)-invocation_started_at)*1000, 2),
                "progress_settle_ms": round((completed_at-(result_sent_at or completed_at))*1000, 2),
                "server_total_ms": round((completed_at-request_received_at)*1000, 2),
                "llm_planning_ms": max((x.get("latency_ms", 0) for x in complete_records
                                        if x.get("operation") == "strands_agents_as_tools_plan"), default=0),
                "specialists": {x.get("component"): x.get("latency_ms") for x in complete_records
                                if x.get("kind") == "agent" and x.get("latency_ms") is not None},
                "private_tools": {x.get("operation"): x.get("latency_ms") for x in complete_records
                                  if x.get("kind") == "tool" and x.get("latency_ms") is not None},
            }
            logger.info(json.dumps({"event": "carecircle_web_timing", "session_id": session_id, **timing}))
            await queue.put({"type": "timing", "value": timing, "trace_id": session_id})
            await queue.put({"type": "done"})

        asyncio.create_task(run())
        return JSONResponse({"job_id": job_id, "session_id": session_id}, status_code=202)

    async def job_events(request):
        job_id = request.path_params["job_id"]
        queue = jobs.get(job_id)
        if queue is None:
            return JSONResponse({"error": "UnknownJob"}, status_code=404)

        async def stream():
            try:
                while True:
                    item = await queue.get()
                    yield f"data: {json.dumps(item)}\n\n"
                    if item["type"] == "done":
                        break
            finally:
                jobs.pop(job_id, None)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return Starlette(routes=[
        Route("/", index), Route("/app.js", script), Route("/api/mcp", api, methods=["POST"]),
        Route("/api/transcribe", transcribe, methods=["POST"]),
        Route("/api/speak", speak, methods=["POST"]),
        Route("/api/voice-intent", voice_intent, methods=["POST"]),
        Route("/api/jobs", start_job, methods=["POST"]),
        Route("/api/jobs/{job_id}/events", job_events),
    ])


def main():
    import uvicorn
    uvicorn.run(create_web_app(), host="127.0.0.1", port=int(os.getenv("CARECIRCLE_WEB_PORT", "8765")))


if __name__ == "__main__":
    main()
