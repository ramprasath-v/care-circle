"""Read only the synthetic hero household's authoritative briefing inputs."""
import asyncio
import os

import boto3

from carecircle.internal_tools import HomeSafetyTools
from carecircle.providers.ring import SimulatedRingProvider
from carecircle.remote import RemoteCareCircle
from carecircle.state import DynamoStateStore, is_current_demo_event


def main():
    profile_name = os.getenv('AWS_PROFILE', 'carecircle-admin')
    region = os.getenv('AWS_REGION', 'us-east-1')
    session = boto3.Session(profile_name=profile_name, region_name=region)
    store = DynamoStateStore('CareCircleCareProfiles', 'CareCircleCareEvents', 'CareCircleActionLedger',
                             dynamodb=session.resource('dynamodb'))
    household = 'demo-household'
    profile = store.get_profile(household)
    if profile is None:
        raise RuntimeError('DemoProfileMissing')
    ring = SimulatedRingProvider(store)
    home = HomeSafetyTools(store, ring)

    async def reads():
        return (await ring.stove_status(household),
                (await home.get_stove_or_smart_plug_status(household)).data['status'],
                (await home.run_home_safety_sweep(household)).data['stove']['status'])

    ring_status, private_status, sweep_status = asyncio.run(reads())
    events = store.list_events(household)
    incidents = store.list_incidents(household)
    device_actions = [action for incident in incidents for action in store.list_actions(incident['incident_id'])
                      if action.get('type') == 'device_change']
    remote = None
    if os.getenv('AGENT_RUNTIME_ARN'):
        remote = RemoteCareCircle(os.environ['AGENT_RUNTIME_ARN'], profile_name, region).call(
            'get_household_briefing', {'household_id': household, 'session_id': 'voice-briefing-probe'})
    print({
        'profile_generation': profile.get('demo_started_at'),
        'careprofiles_plug': next((x.get('state') for x in profile.get('devices', []) if x.get('id') == 'stove-plug'), None),
        'careprofiles_tasks': [(x['id'], x['status'], x.get('owner')) for x in profile.get('care_tasks', [])],
        'careevents_doses': [(x.get('event_id'), x.get('status'), is_current_demo_event(profile, x))
                             for x in events if x.get('kind') == 'dose_status'],
        'careevents_walk': [(x.get('event_id'), x.get('status'), is_current_demo_event(profile, x))
                            for x in events if x.get('kind') == 'routine_exception'],
        'actionledger_device_actions': [(x['action_id'], x.get('execution_state'), x.get('approval_state'))
                                        for x in device_actions],
        'actionledger_incidents': [(x['incident_id'], x.get('session_id'), x.get('resolution_state')) for x in incidents],
        'ring_provider': ring_status['smart_plug'],
        'private_get_stove_or_smart_plug_status': private_status['smart_plug'],
        'private_run_home_safety_sweep': sweep_status['smart_plug'],
        'remote_briefing_plug': remote['home_status']['stove']['status']['smart_plug'] if remote else None,
        'remote_briefing_medication_unresolved': len(remote['medication_status']['unresolved']) if remote and remote.get('medication_status') else None,
        'remote_briefing_open_tasks': [(x['id'], x['status']) for x in remote['open_care_tasks']] if remote else None,
        'remote_briefing_care_team': [(x['name'], x['on_call']) for x in remote['care_team']] if remote else None,
        'remote_briefing_appointment': (remote['next_appointment']['name'], remote['next_appointment']['time']) if remote and remote.get('next_appointment') else None,
        'remote_briefing_routine_deviations': len(remote['routine_deviations']) if remote else None,
    })


if __name__ == '__main__':
    main()
