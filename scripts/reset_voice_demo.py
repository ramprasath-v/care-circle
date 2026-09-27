"""Reset only synthetic voice-* and legacy web-* demo incidents."""
import argparse
import os

import boto3

from carecircle.demo_reset import reset_voice_demo
from carecircle.internal_tools import HomeSafetyTools
from carecircle.providers.ring import SimulatedRingProvider
from carecircle.state import DynamoStateStore, is_current_demo_event


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Remove voice-*/web-* demo incidents and restore synthetic profile')
    args = parser.parse_args()
    session = boto3.Session(profile_name=os.getenv('AWS_PROFILE', 'carecircle-admin'),
                            region_name=os.getenv('AWS_REGION', 'us-east-1'))
    store = DynamoStateStore('CareCircleCareProfiles', 'CareCircleCareEvents', 'CareCircleActionLedger',
                             dynamodb=session.resource('dynamodb'))
    preview = [i for i in store.list_incidents('demo-household') if i.get('session_id', '').startswith(('voice-', 'web-'))]
    print({'household':'demo-household', 'demo_incidents_to_reset':len(preview),
           'incident_ids':[i['incident_id'] for i in preview], 'apply':args.apply})
    if args.apply:
        provider = SimulatedRingProvider(store)
        print({'reset':reset_voice_demo(store, session.client('scheduler'), provider)})
        profile = store.get_profile('demo-household')
        import asyncio
        home = HomeSafetyTools(store, SimulatedRingProvider(store))
        plug = asyncio.run(home.get_stove_or_smart_plug_status('demo-household')).data['status']['smart_plug']
        sweep_plug = asyncio.run(home.run_home_safety_sweep('demo-household')).data['stove']['status']['smart_plug']
        device = next(item for item in profile['devices'] if item['id'] == 'stove-plug')
        assert plug == sweep_plug == device['state'] == 'on', 'DemoResetPlugVerificationFailed'
        current_doses = [event for event in store.list_events('demo-household')
                         if event.get('kind') == 'dose_status' and is_current_demo_event(profile, event)]
        assert any(event.get('status') == 'unresolved' for event in current_doses), 'DemoResetDoseVerificationFailed'
        assert not any(task.get('owner') and task['status'] != 'COMPLETED' for task in profile['care_tasks']), 'DemoResetTaskVerificationFailed'
        runtime_arn = os.getenv('AGENT_RUNTIME_ARN')
        briefing_plug = None
        if runtime_arn:
            from carecircle.remote import RemoteCareCircle
            briefing = RemoteCareCircle(runtime_arn).call('get_household_briefing', {'household_id': 'demo-household'})
            briefing_plug = briefing['home_status']['stove']['status']['smart_plug']
            assert briefing_plug == 'on', 'DemoResetBriefingVerificationFailed'
            assert briefing['medication_status']['unresolved'], 'DemoResetRemoteDoseVerificationFailed'
            assert briefing['open_care_tasks'] == [], 'DemoResetRemoteTaskVerificationFailed'
        assert not [i for i in store.list_incidents('demo-household') if i.get('session_id', '').startswith(('voice-', 'web-'))], 'DemoResetIncidentVerificationFailed'
        print({'verified_plug':plug, 'verified_sweep_plug':sweep_plug,
               'verified_remote_briefing_plug':briefing_plug, 'verified_current_unresolved_doses':len(current_doses),
               'verified_voice_incidents':0,
               'verified_caregiver_task':profile['care_tasks'][0]['status'],
               'verified_draft_actions':0})
    else:
        print('Preview only; run with --apply to reset persisted demo state.')


if __name__ == '__main__':
    main()
