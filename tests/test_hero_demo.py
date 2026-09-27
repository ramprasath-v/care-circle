"""One continuous four-tool MCP demo must actually execute all 28 private tools."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from carecircle.demo_reset import reset_voice_demo
from carecircle.full_supervisor import FullCareCircleSupervisor
from carecircle.full_supervisor import _spoken_safety_answers
from carecircle.internal_tools import INTERNAL_TOOL_OWNERS, CareCoordinatorTools, HomeSafetyTools, LogisticsRoutineTools, MedicationTools, TriageTools
from carecircle.providers.aws_actions import RecordingAlertProvider, RecordingSchedulerProvider
from carecircle.providers.ring import SimulatedRingProvider
from carecircle.schemas import CareResponse, IncidentStatus, TriageResult
from carecircle.state import InMemoryStateStore
from carecircle.workflow import ActionWorkflow
from test_full_mcp import call, client_for


@pytest.fixture
def demo(triage_result):
    store = InMemoryStateStore()
    ring = SimulatedRingProvider(store)
    alerts, scheduler = RecordingAlertProvider(), RecordingSchedulerProvider()
    triage = TriageTools(store)
    medication = MedicationTools(store)
    home = HomeSafetyTools(store, ring)
    coordinator = CareCoordinatorTools(store, alerts, scheduler)
    logistics = LogisticsRoutineTools(store)
    workflow = ActionWorkflow(store, alerts, scheduler, ring)
    agent = SimpleNamespace(assess=AsyncMock(return_value=triage_result))
    supervisor = FullCareCircleSupervisor(agent, store, triage, medication, home, coordinator, logistics, workflow)
    return SimpleNamespace(store=store, ring=ring, alerts=alerts, scheduler=scheduler, supervisor=supervisor)


@pytest.mark.asyncio
async def test_reset_reseeds_current_medication_and_briefing_runs_specialists(demo, caplog):
    caplog.set_level(logging.INFO, logger='carecircle')
    old = demo.store.get_profile('demo-household')
    old['devices'][1]['state'] = 'off'
    old['care_tasks'][0].update(status='COMPLETED', owner='john')
    demo.store.put_profile('demo-household', old)
    demo.store.put_event('demo-household', 'old-taken', {'event_id':'old-taken', 'kind':'dose_status',
        'medication_id':'med-heart-001', 'status':'taken', 'timestamp':'2026-01-01T00:00:00+00:00'})
    reset_voice_demo(demo.store, ring_provider=demo.ring)
    profile = demo.store.get_profile('demo-household')
    assert next(x['state'] for x in profile['devices'] if x['id'] == 'stove-plug') == 'on'
    assert not any(x.get('owner') for x in profile['care_tasks'])
    assert any(x['status'] == 'unresolved' and x['timestamp'] >= profile['demo_started_at']
               for x in demo.store.list_events('demo-household') if x['kind'] == 'dose_status')
    async with client_for(demo.supervisor) as client:
        briefing = await call(client, 'get_household_briefing',
                              {'household_id':'demo-household', 'session_id':'voice-briefing-specialists'})
    assert briefing['medication_status']['unresolved']
    assert briefing['home_status']['stove']['status']['smart_plug'] == 'on'
    assert briefing['open_care_tasks'] == []
    assert [(x['name'], x['on_call']) for x in briefing['care_team']] == [('Maya', False), ('John', True)]
    assert briefing['next_appointment']['time'] == '14:30'
    assert not demo.store.list_incidents('demo-household')
    events = [json.loads(record.message) for record in caplog.records if '"carecircle_progress"' in record.message]
    completed = {(x['component'], x['operation']) for x in events if x['status'] == 'COMPLETE'}
    assert {'CareCircle Supervisor', 'Medication Agent', 'Home Safety Agent',
            'Care Coordinator Agent', 'Logistics & Routine Agent'} <= {name for name, _ in completed}
    assert not any(name == 'Triage Agent' for name, _ in completed)
    assert {'get_medication_schedule', 'get_dose_history', 'find_missed_doses', 'get_medication_inventory',
            'get_recent_ring_events', 'get_entry_activity_summary', 'get_smoke_co_status',
            'get_stove_or_smart_plug_status', 'run_home_safety_sweep', 'get_care_team',
            'get_upcoming_appointments', 'get_daily_routine', 'get_pharmacy_details'} <= {tool for _, tool in completed}


@pytest.mark.asyncio
async def test_existing_simulator_discards_old_device_result_on_demo_generation_change(demo):
    await demo.ring.execute_device_action('demo-household', 'stove-plug', 'turn_off')
    assert demo.ring.executed
    reset_voice_demo(demo.store)
    assert (await demo.ring.stove_status('demo-household'))['smart_plug'] == 'on'
    assert not demo.ring.executed


@pytest.mark.asyncio
async def test_store_backed_provider_never_invents_on_for_missing_device(demo):
    profile = demo.store.get_profile('demo-household')
    profile['devices'] = []
    demo.store.put_profile('demo-household', profile)
    assert (await demo.ring.stove_status('demo-household'))['smart_plug'] == 'unavailable'


@pytest.mark.asyncio
async def test_reset_plug_stays_on_until_explicit_device_confirmation(demo):
    household = 'demo-household'
    async with client_for(demo.supervisor) as client:
        async def invoke(name, **kwargs):
            return await call(client, name, {'household_id': household, **kwargs})
        first = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-old',
                             utterance="Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.")
        incident = first['incident_id']
        if first.get('awaiting_safety_answers'):
            first = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-old',
                                 incident_id=incident, utterance='He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.')
        assert first['proposed_actions']
        await invoke('confirm_action', incident_id=incident, action_id=first['proposed_actions'][0]['action_id'], approved=True)
        device = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-old',
                              incident_id=incident, utterance="Turn off Dad's kitchen smart plug.")
        await invoke('confirm_action', incident_id=incident, action_id=device['proposed_actions'][0]['action_id'], approved=True)
        assert (await demo.ring.stove_status(household))['smart_plug'] == 'off'
        assert demo.ring.executed

        reset_voice_demo(demo.store, ring_provider=demo.ring)
        assert not demo.ring.executed and demo.ring._plug_state == 'on'
        assert (await SimulatedRingProvider(demo.store).stove_status(household))['smart_plug'] == 'on'
        assert (await demo.supervisor.home.tools.get_stove_or_smart_plug_status(household)).data['status']['smart_plug'] == 'on'
        briefing = await invoke('get_household_briefing', session_id='voice-reset-new')
        assert briefing['home_status']['stove']['status']['smart_plug'] == 'on'

        concern = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-new',
                               utterance="Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.")
        incident = concern['incident_id']
        if concern.get('awaiting_safety_answers'):
            concern = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-new',
                                   incident_id=incident, utterance='He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.')
        assert (await invoke('get_incident_status', incident_id=incident))['home_smart_plug'] == 'on'
        await invoke('confirm_action', incident_id=incident, action_id=concern['proposed_actions'][0]['action_id'], approved=True)
        assert (await demo.ring.stove_status(household))['smart_plug'] == 'on'
        drafts = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-new',
                              incident_id=incident, utterance="Also help with the rest of Dad's day.")
        for action in drafts['proposed_actions']:
            await invoke('confirm_action', incident_id=incident, action_id=action['action_id'], approved=True)
        assert (await demo.ring.stove_status(household))['smart_plug'] == 'on'
        device = await invoke('coordinate_care_request', actor_role='caregiver', session_id='voice-reset-new',
                              incident_id=incident, utterance="Turn off Dad's kitchen smart plug.")
        assert (await invoke('get_incident_status', incident_id=incident))['home_smart_plug'] == 'on'
        await invoke('confirm_action', incident_id=incident, action_id=device['proposed_actions'][0]['action_id'], approved=True)
        assert (await demo.ring.stove_status(household))['smart_plug'] == 'off'
        assert (await invoke('get_incident_status', incident_id=incident))['home_smart_plug'] == 'off'


@pytest.mark.asyncio
async def test_full_demo_four_public_mcp_tools_and_28_real_private_tool_events(demo, caplog):
    caplog.set_level(logging.INFO, logger='carecircle')
    profile = demo.store.get_profile('demo-household')
    assert profile['person']['name'] == 'Robert'
    assert profile['medications'][0]['inventory_count'] == 4
    assert profile['care_team'][0]['on_call'] is False and profile['care_team'][1]['on_call'] is True
    assert (await demo.ring.stove_status('demo-household'))['smart_plug'] == 'on'
    seen_public = set()
    async with client_for(demo.supervisor) as client:
        async def invoke(name, args):
            seen_public.add(name)
            return await call(client, name, args)
        briefing = await invoke('get_household_briefing', {'household_id':'demo-household','session_id':'voice-test-brief'})
        assert briefing['medication_status']['unresolved']
        assert briefing['home_status']['stove']['status']['smart_plug'] == 'on'
        assert briefing['next_appointment']['time'] == '14:30'
        assert briefing['routine_deviations'][0]['routine_id'] == 'walk'
        assert [(person['name'], person['on_call']) for person in briefing['care_team']] == [('Maya', False), ('John', True)]
        response = CareResponse.model_validate(await invoke('coordinate_care_request', {
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-test-incident',
            'utterance':"Dad just called. He seems confused and isn't sure whether he took his medication. Maya isn't available. Please coordinate help."}))
        incident_id = response.incident_id
        assert response.approval_required and len(response.proposed_actions) == 1
        before_alert = IncidentStatus.model_validate_json(json.dumps(await invoke('get_incident_status', {
            'household_id':'demo-household','incident_id':incident_id})))
        assert before_alert.medication_status == 'unresolved'
        assert before_alert.home_smart_plug == 'on'
        assert before_alert.assigned_caregiver == 'john'
        assert before_alert.care_task_status == 'ASSIGNED'
        caregiver_action = response.proposed_actions[0].action_id
        assert demo.store.get_incident(incident_id)['safety_answers']['new_or_worsening_confusion']
        assert demo.store.get_action(incident_id, caregiver_action)['owner'] == 'john'
        assert not demo.alerts.sent
        args = {'household_id':'demo-household','incident_id':incident_id,'action_id':caregiver_action,'approved':True,'session_id':'voice-test-alert'}
        approved = await invoke('confirm_action', args)
        assert approved['execution_state'] == 'COMPLETED' and approved['next_check_at']
        after_alert = IncidentStatus.model_validate_json(json.dumps(await invoke('get_incident_status', {
            'household_id':'demo-household','incident_id':incident_id})))
        assert after_alert.medication_status == 'unresolved'
        assert after_alert.home_smart_plug == 'on'
        assert after_alert.care_task_status == 'ASSIGNED'
        await invoke('confirm_action', {**args,'session_id':'voice-test-alert-repeat'})
        assert len(demo.alerts.sent) == 1 and len(demo.scheduler.scheduled) == 1
        device = CareResponse.model_validate(await invoke('coordinate_care_request', {
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-test-device','incident_id':incident_id,
            'utterance':"Turn off Dad's kitchen smart plug."}))
        assert device.incident_id == incident_id and len(device.proposed_actions) == 1 and not demo.ring.executed
        before_device_approval = IncidentStatus.model_validate_json(json.dumps(await invoke('get_incident_status', {
            'household_id':'demo-household','incident_id':incident_id})))
        assert before_device_approval.home_smart_plug == 'on'
        assert before_device_approval.medication_status == 'unresolved'
        await invoke('confirm_action', {'household_id':'demo-household','incident_id':incident_id,
            'action_id':device.proposed_actions[0].action_id,'approved':True,'session_id':'voice-test-device-approve'})
        assert (await demo.ring.stove_status('demo-household'))['smart_plug'] == 'off'
        after_device_approval = IncidentStatus.model_validate_json(json.dumps(await invoke('get_incident_status', {
            'household_id':'demo-household','incident_id':incident_id})))
        assert after_device_approval.home_smart_plug == 'off'
        assert after_device_approval.medication_status == 'unresolved'
        drafts = CareResponse.model_validate(await invoke('coordinate_care_request', {
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-test-drafts','incident_id':incident_id,
            'utterance':"Also help with the rest of Dad's day."}))
        assert 'Prepared drafts' in drafts.summary
        types = {a['type'] for a in demo.store.list_actions(incident_id) if a['execution_state'] == 'DRAFT'}
        assert types == {'refill_draft','ride_draft','supply_draft'}
        draft_ids = [a['action_id'] for a in demo.store.list_actions(incident_id) if a['type'] in types]
        prior_alerts, prior_schedules, prior_device_actions = len(demo.alerts.sent), len(demo.scheduler.scheduled), len(demo.ring.executed)
        for action_id in draft_ids:
            confirmation = await invoke('confirm_action', {'household_id':'demo-household','incident_id':incident_id,
                'action_id':action_id,'approved':True,'session_id':f'voice-draft-{action_id}'})
            assert confirmation['execution_state'] == 'DRAFT'
            assert confirmation['provider_result']['status'] == 'approved_draft'
        approved_drafts = [a for a in demo.store.list_actions(incident_id) if a['type'] in types]
        assert all(a['approval_state'] == 'APPROVED' and a['execution_state'] == 'DRAFT' for a in approved_drafts)
        assert (len(demo.alerts.sent), len(demo.scheduler.scheduled), len(demo.ring.executed)) == (prior_alerts, prior_schedules, prior_device_actions)
        draft_status = IncidentStatus.model_validate_json(json.dumps(await invoke('get_incident_status', {
            'household_id':'demo-household','incident_id':incident_id})))
        assert draft_status.medication_status == 'unresolved' and draft_status.home_smart_plug == 'off'
        resolved = CareResponse.model_validate(await invoke('coordinate_care_request', {
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-test-resolve','incident_id':incident_id,
            'utterance':"John checked on Dad. Dad is okay and confirmed he already took his morning medication."}))
        assert resolved.incident_id == incident_id
        status = IncidentStatus.model_validate_json(json.dumps(await invoke('get_incident_status', {
            'household_id':'demo-household','incident_id':incident_id,'session_id':'voice-test-status'})))
        assert status.status == 'RESOLVED' and status.resolution_state == 'RESOLVED'
        assert status.medication_status == 'taken' and status.care_task_status == 'COMPLETED'
        assert status.home_smart_plug == 'off' and status.assigned_caregiver == 'john'
        assert len(status.draft_actions) == 3 and len(status.completed_actions) == 2
        assert status.next_appointment['time'] == '14:30'
    tool_events = [json.loads(r.message) for r in caplog.records if '"carecircle_progress"' in r.message]
    exercised = {e['operation'] for e in tool_events if e.get('kind') == 'tool' and e['status'] == 'COMPLETE'}
    assert exercised == set(INTERNAL_TOOL_OWNERS), sorted(set(INTERNAL_TOOL_OWNERS)-exercised)
    assert seen_public == {'coordinate_care_request','get_household_briefing','confirm_action','get_incident_status'}
    assert len(demo.store.list_incidents('demo-household')) == 1
    reset = reset_voice_demo(demo.store)
    assert reset['incidents'] == 1
    assert not demo.store.list_incidents('demo-household')
    assert (await demo.ring.stove_status('demo-household'))['smart_plug'] == 'on'
    assert (await demo.supervisor.home.tools.get_stove_or_smart_plug_status('demo-household')).data['status']['smart_plug'] == 'on'
    assert demo.store.get_profile('demo-household')['care_tasks'][0]['status'] == 'OPEN'
    assert demo.store.get_profile('demo-household')['care_tasks'][0]['owner'] is None
    assert demo.store.list_events('demo-household')[0]['kind'] in {'dose_status','routine_exception'}
    assert all(e.get('status') != 'taken' for e in demo.store.list_events('demo-household'))


@pytest.mark.asyncio
async def test_safety_question_answer_continues_same_incident(demo, triage_result):
    triage_result.safety_questions = ['Is the person awake and responsive?']
    async with client_for(demo.supervisor) as client:
        first = CareResponse.model_validate(await call(client,'coordinate_care_request',{
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-question',
            'utterance':'Dad is newly confused and may have missed medication.'}))
        assert not first.approval_required and 'awake and responsive' in first.summary
        partial = CareResponse.model_validate(await call(client,'coordinate_care_request',{
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-answer','incident_id':first.incident_id,
            'utterance':'He is awake and responsive. No chest pain or breathing trouble. The confusion is new.'}))
        assert partial.incident_id == first.incident_id and partial.awaiting_safety_answers
        assert partial.summary == 'Does Dad have trouble speaking?'
        assert partial.risk_level == 'unknown' and not partial.approval_required
        persisted = demo.store.get_incident(first.incident_id)
        assert persisted['safety_answers']['awake_and_responsive'] is True
        assert persisted['safety_answers']['chest_pain'] is False
        assert persisted['safety_answers']['severe_trouble_breathing'] is False
        second = CareResponse.model_validate(await call(client,'coordinate_care_request',{
            'household_id':'demo-household','actor_role':'caregiver','session_id':'voice-answer','incident_id':first.incident_id,
            'utterance':'No trouble speaking.'}))
        assert second.incident_id == first.incident_id and second.approval_required
        assert not second.awaiting_safety_answers
        assert demo.store.get_incident(first.incident_id)['safety_answers']['awake_and_responsive'] is True
        assert len(demo.store.list_incidents('demo-household')) == 1


@pytest.mark.asyncio
async def test_complete_safety_answer_then_yes_uses_one_incident(demo, triage_result):
    triage_result.safety_questions = ['Is the person awake and responsive?']
    async with client_for(demo.supervisor) as client:
        first = CareResponse.model_validate(await call(client, 'coordinate_care_request', {
            'household_id': 'demo-household', 'actor_role': 'caregiver', 'session_id': 'voice-one-session',
            'utterance': "Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help."}))
        assert first.awaiting_safety_answers and first.risk_level == 'unknown'
        answer = CareResponse.model_validate(await call(client, 'coordinate_care_request', {
            'household_id': 'demo-household', 'actor_role': 'caregiver', 'session_id': 'voice-one-session',
            'incident_id': first.incident_id,
            'utterance': 'He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.'}))
        persisted = demo.store.get_incident(first.incident_id)
        assert answer.incident_id == first.incident_id and not answer.awaiting_safety_answers
        assert answer.approval_required and len(answer.proposed_actions) == 1
        assert persisted['awaiting_safety_answers'] is False
        assert persisted['safety_answers'] == {'new_or_worsening_confusion': True,
            'severe_trouble_breathing': False, 'chest_pain': False,
            'difficulty_speaking': False, 'awake_and_responsive': True}
        action = answer.proposed_actions[0]
        approved = await call(client, 'confirm_action', {'household_id': 'demo-household',
            'incident_id': first.incident_id, 'action_id': action.action_id,
            'approved': True, 'session_id': 'voice-one-session'})
        assert approved['execution_state'] == 'COMPLETED'
        assert len(demo.store.list_incidents('demo-household')) == 1
        assert demo.store.get_incident(first.incident_id)['safety_answers']['awake_and_responsive'] is True


def test_explicit_safety_negation_and_scoped_reset(demo):
    answers = _spoken_safety_answers('He is awake and responsive. No chest pain or difficulty breathing. The confusion is new.')
    assert answers.awake_and_responsive is True and answers.chest_pain is False
    assert answers.severe_trouble_breathing is False and answers.new_or_worsening_confusion is True
    assert _spoken_safety_answers('He is not awake and responsive.').awake_and_responsive is False
    assert _spoken_safety_answers('He has chest pain.').chest_pain is True
    complete = _spoken_safety_answers('He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.')
    assert complete.model_dump() == {'severe_trouble_breathing': False, 'chest_pain': False,
        'difficulty_speaking': False, 'awake_and_responsive': True, 'new_or_worsening_confusion': True}
    short = _spoken_safety_answers("Yes, he's awake and responsive. No chest pain or breathing problems.")
    assert short.awake_and_responsive is True and short.chest_pain is False
    assert short.severe_trouble_breathing is False and short.difficulty_speaking is None
    import asyncio
    async def create():
        unrelated = await demo.supervisor.triage.create_incident('demo-household', 'full-build-remote-demo', 'Older test')
        voice = await demo.supervisor.triage.create_incident('demo-household', 'voice-new-demo', 'Hero')
        web = await demo.supervisor.triage.create_incident('demo-household', 'web-old-demo', 'Legacy browser demo')
        return unrelated.data['incident']['incident_id'], voice.data['incident']['incident_id'], web.data['incident']['incident_id']
    unrelated_id, voice_id, web_id = asyncio.run(create())
    assert reset_voice_demo(demo.store)['incidents'] == 2
    assert demo.store.get_incident(unrelated_id) is not None
    assert demo.store.get_incident(voice_id) is None
    assert demo.store.get_incident(web_id) is None


@pytest.mark.asyncio
async def test_reset_and_new_incident_ignore_prior_dose_and_device_state(demo):
    old = await demo.supervisor.triage.create_incident('demo-household', 'full-build-remote-demo', 'Old synthetic run')
    old_id = old.data['incident']['incident_id']
    await demo.supervisor.medication.record_dose_status('demo-household', 'med-heart-001', 'taken', 'old-dose-taken', old_id)
    old_profile = demo.store.get_profile('demo-household')
    old_profile['devices'][1]['state'] = 'off'
    old_profile['care_tasks'][0].update(status='COMPLETED', owner='john')
    demo.store.put_profile('demo-household', old_profile)
    voice = await demo.supervisor.triage.create_incident('demo-household', 'voice-previous', 'Old voice demo')
    assert reset_voice_demo(demo.store)['incidents'] == 1
    assert demo.store.get_incident(voice.data['incident']['incident_id']) is None
    assert demo.store.get_incident(old_id) is not None

    profile = demo.store.get_profile('demo-household')
    assert profile['devices'][1]['state'] == 'on'
    assert profile['care_tasks'][0]['status'] == 'OPEN' and profile['care_tasks'][0]['owner'] is None
    assert [x['on_call'] for x in profile['care_team']] == [False, True]
    assert profile['appointments'][0]['time'] == '14:30'
    briefing = await demo.supervisor.briefing('demo-household')
    assert briefing.medication_status['unresolved']
    assert briefing.home_status['stove']['status']['smart_plug'] == 'on'
    assert briefing.unresolved_incidents == []
    assert (await demo.supervisor.home.tools.get_stove_or_smart_plug_status('demo-household')).data['status']['smart_plug'] == 'on'
    assert demo.ring._plug_state == 'on'
    fresh = await demo.supervisor.triage.create_incident('demo-household', 'voice-new', 'New hero demo')
    fresh_id = fresh.data['incident']['incident_id']
    status = demo.supervisor.workflow.status('demo-household', fresh_id)
    assert status.medication_status == 'unresolved' and status.home_smart_plug == 'on'
    assert status.care_task_status == 'OPEN' and status.assigned_caregiver is None
    assert status.draft_actions == [] and status.completed_actions == []
    assert demo.supervisor.workflow.status('demo-household', old_id).medication_status == 'taken'
