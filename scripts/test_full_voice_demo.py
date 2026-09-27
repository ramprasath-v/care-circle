"""Live seven-scene CareCircle demo through the four public MCP tools and SSE bridge.

Run reset_voice_demo.py --apply first. This script creates a synthetic incident,
SNS demo-inbox alert, one-shot follow-up, a simulated device action and drafts.
"""
import asyncio
import json
import os
from time import perf_counter

import httpx

from carecircle.internal_tools import INTERNAL_TOOL_OWNERS
from carecircle.schemas import CareResponse, IncidentStatus
from carecircle.web import create_web_app


async def main():
    assert os.environ.get('AGENT_RUNTIME_ARN'), 'Set AGENT_RUNTIME_ARN'
    app = create_web_app()
    tools = set()
    public = set()
    agents = set()
    start_all = perf_counter()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost', timeout=180) as web:
        async def call(name, arguments):
            started = perf_counter()
            reply = await web.post('/api/jobs', json={'operation':name, 'arguments':arguments})
            reply.raise_for_status()
            stream = await web.get(f"/api/jobs/{reply.json()['job_id']}/events")
            stream.raise_for_status()
            messages = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith('data: ')]
            final = next((m for m in messages if m['type'] == 'result'), None)
            if final is None:
                raise RuntimeError(f'{name}: {next((m for m in messages if m["type"] == "error"), "NoResult")}')
            for event in messages:
                if event.get('type') != 'progress':
                    continue
                if event.get('kind') == 'tool' and event.get('status') == 'COMPLETE':
                    tools.add(event['operation'])
                if event.get('component') in {'CareCircle Supervisor','Triage Agent','Medication Agent',
                    'Home Safety Agent','Care Coordinator Agent','Logistics & Routine Agent'}:
                    agents.add(event['component'])
            public.add(name)
            print({'scene':name,'latency_ms':round((perf_counter()-started)*1000),
                   'progress_events':sum(m['type']=='progress' for m in messages),'tools_observed':len(tools)})
            return final['value']
        base = {'household_id':'demo-household'}
        briefing = await call('get_household_briefing', base)
        assert briefing['home_status']['stove']['status']['smart_plug'] == 'on'
        assert briefing['medication_status']['unresolved']
        assert briefing['routine_deviations'] and briefing['routine_deviations'][0]['routine_id'] == 'walk'
        assert [(person['name'], person['on_call']) for person in briefing['care_team']] == [('Maya', False), ('John', True)]
        concern = CareResponse.model_validate(await call('coordinate_care_request', {**base,'actor_role':'caregiver',
            'utterance':"Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help."}))
        incident_id = concern.incident_id
        if not concern.proposed_actions:
            assert concern.awaiting_safety_answers and 'awake and responsive' in concern.summary.lower()
            concern = CareResponse.model_validate(await call('coordinate_care_request', {**base,'actor_role':'caregiver',
                'incident_id':incident_id,'utterance':'He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.'}))
        assert concern.incident_id == incident_id and len(concern.proposed_actions) == 1 and not concern.awaiting_safety_answers
        selected = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
        assert selected.assigned_caregiver == 'john' and selected.care_task_status == 'ASSIGNED'
        assert selected.medication_status == 'unresolved' and selected.home_smart_plug == 'on'
        caregiver_action = concern.proposed_actions[0].action_id
        approval = await call('confirm_action', {**base,'incident_id':incident_id,'action_id':caregiver_action,'approved':True})
        assert approval['execution_state'] == 'COMPLETED' and approval['provider_result']['provider'] == 'sns'
        assert approval['next_check_at']
        alert_status = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
        assert alert_status.care_task_status == 'ASSIGNED'
        assert alert_status.medication_status == 'unresolved' and alert_status.home_smart_plug == 'on'
        repeated = await call('confirm_action', {**base,'incident_id':incident_id,'action_id':caregiver_action,'approved':True})
        assert repeated['provider_result']['message_id'] == approval['provider_result']['message_id']
        drafts = CareResponse.model_validate(await call('coordinate_care_request', {**base,'actor_role':'caregiver',
            'incident_id':incident_id,'utterance':"Also help with the rest of Dad's day."}))
        assert drafts.incident_id == incident_id and not drafts.approval_required
        draft_status = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
        pending_drafts = [action for action in draft_status.pending_actions if action.type in {'refill_draft','ride_draft','supply_draft'}]
        assert len(pending_drafts) == 3
        decision = (await web.post('/api/voice-intent', json={'transcript':'Approve all','pending_count':len(pending_drafts)})).json()['decision']
        assert decision == 'APPROVE_ALL'
        for action in pending_drafts:
            confirmation = await call('confirm_action', {**base,'incident_id':incident_id,'action_id':action.action_id,'approved':True})
            assert confirmation['execution_state'] == 'DRAFT' and confirmation['provider_result']['status'] == 'approved_draft'
            refreshed = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
            assert refreshed.medication_status == 'unresolved' and refreshed.home_smart_plug == 'on'
        assert all(action.approval_state == 'APPROVED' and action.execution_state == 'DRAFT' for action in refreshed.draft_actions)
        assert len(refreshed.completed_actions) == 1
        device = CareResponse.model_validate(await call('coordinate_care_request', {**base,'actor_role':'caregiver',
            'incident_id':incident_id,'utterance':"Turn off Dad's kitchen smart plug."}))
        assert len(device.proposed_actions) == 1
        pending_device = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
        assert pending_device.home_smart_plug == 'on' and pending_device.medication_status == 'unresolved'
        device_confirmation = await call('confirm_action', {**base,'incident_id':incident_id,
            'action_id':device.proposed_actions[0].action_id,'approved':True})
        assert device_confirmation['execution_state'] == 'COMPLETED'
        approved_device = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
        assert approved_device.home_smart_plug == 'off' and approved_device.medication_status == 'unresolved'
        resolved = CareResponse.model_validate(await call('coordinate_care_request', {**base,'actor_role':'caregiver',
            'incident_id':incident_id,'utterance':'John checked on Dad. Dad is okay and confirmed he already took his morning medication.'}))
        assert resolved.incident_id == incident_id
        final = IncidentStatus.model_validate_json(json.dumps(await call('get_incident_status', {**base,'incident_id':incident_id})))
        assert final.resolution_state == 'RESOLVED' and final.medication_status == 'taken'
        assert final.home_smart_plug == 'off' and final.care_task_status == 'COMPLETED'
        assert final.assigned_caregiver == 'john'
        assert len(final.draft_actions) == 3 and all(x.execution_state == 'DRAFT' and x.approval_state == 'APPROVED' for x in final.draft_actions)
        assert len(final.completed_actions) >= 2 and final.next_appointment['time'] == '14:30'
        audio = await web.post('/api/speak', json={'text':'Dad’s reported morning dose and caregiver check are recorded. The prepared requests remain drafts.'})
        audio.raise_for_status()
        assert audio.headers['content-type'].startswith('audio/mpeg') and len(audio.content) > 1000
    print(json.dumps({'incident_id':incident_id,'agents_exercised':len(agents),'private_tools_exercised':len(tools),
          'public_mcp_tools_exercised':len(public),'missing_tools':sorted(set(INTERNAL_TOOL_OWNERS)-tools),
          'sns_message_id':approval['provider_result']['message_id'],
          'follow_up':approval['next_check_at'],'plug':final.home_smart_plug,
          'dose':final.medication_status,'draft_types':sorted(x.type for x in final.draft_actions),
          'polly_bytes':len(audio.content),'total_latency_ms':round((perf_counter()-start_all)*1000)}, indent=2))
    assert len(agents) == 6 and tools == set(INTERNAL_TOOL_OWNERS) and len(public) == 4


if __name__ == '__main__':
    asyncio.run(main())
