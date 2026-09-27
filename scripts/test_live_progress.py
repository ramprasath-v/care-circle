"""Exercise the local SSE bridge against the deployed AgentCore runtime."""
import asyncio
import json
import os
from time import perf_counter

import httpx

from carecircle.schemas import CareResponse
from carecircle.web import create_web_app


async def main():
    app = create_web_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost', timeout=180) as client:
        started = perf_counter()
        reply = await client.post('/api/jobs', json={'operation':'coordinate_care_request', 'arguments':{
            'household_id':'demo-household','actor_role':'caregiver',
            'utterance':'Dad says he may have missed his morning medication and seems confused.'}})
        reply.raise_for_status()
        data = (await client.get(f"/api/jobs/{reply.json()['job_id']}/events")).text
        events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith('data: ')]
        results = [item for item in events if item['type'] == 'result']
        if not results:
            raise RuntimeError(f"MCP result was not successful: {events[-2]}")
        care = CareResponse.model_validate(results[-1]['value'])
        progress = [e for e in events if e.get('type') == 'progress' and e.get('component') != 'AgentCore / MCP']
        print(json.dumps({'session_id':reply.json()['session_id'],'incident_id':care.incident_id,'risk':care.risk_level,
            'approval_required':care.approval_required,'progress_events':len(progress),
            'agents':sorted({e['component'] for e in progress if e.get('component','').endswith('Agent') or e.get('component')=='CareCircle Supervisor'}),
            'tools':sorted({e['operation'] for e in progress if e.get('kind')=='tool' and e.get('status')=='COMPLETE'}),
            'statuses':sorted({e.get('status') for e in progress}),
            'trace_read_failed':any(e.get('operation')=='read_progress' for e in progress),
            'latency_ms':round((perf_counter()-started)*1000)}, indent=2))
        if not progress or any(e.get('operation')=='read_progress' for e in progress):
            raise AssertionError('Runtime CloudWatch progress did not reach SSE')


if __name__ == '__main__':
    asyncio.run(main())
