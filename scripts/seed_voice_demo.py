"""Update only the synthetic demo profile for the voice-day scenario."""
import argparse
import os

import boto3

from carecircle.state import DynamoStateStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='Update only demo-household in CareCircleCareProfiles')
    args = parser.parse_args()
    session = boto3.Session(profile_name=os.getenv('AWS_PROFILE', 'carecircle-admin'),
                            region_name=os.getenv('AWS_REGION', 'us-east-1'))
    store = DynamoStateStore('CareCircleCareProfiles', 'CareCircleCareEvents', 'CareCircleActionLedger', dynamodb=session.resource('dynamodb'))
    profile = store.get_profile('demo-household')
    if not profile or profile.get('household_id') != 'demo-household':
        raise RuntimeError('Synthetic demo household not found; refusing to seed')
    profile['person']['name'] = 'Robert'
    for person in profile['care_team']:
        if person['id'] == 'maya': person['on_call'] = False
        if person['id'] == 'john': person['on_call'] = True
    if not any(item['id'] == 'pill-organizer' for item in profile['care_tasks']):
        profile['care_tasks'].append({'id':'pill-organizer','title':'Get a weekly pill organizer',
                                      'status':'OPEN','owner':'john'})
    if args.apply:
        store.put_profile('demo-household', profile)
    print({'applied':args.apply,'household':'demo-household','person':profile['person']['name'],
           'on_call':[x['name'] for x in profile['care_team'] if x.get('on_call')],
           'pill_organizer_task':True})


if __name__ == '__main__':
    main()
