"""Read recent privacy-safe CloudWatch evidence for a browser briefing turn."""
import json
import os
from time import time

import boto3

from carecircle.live_progress import CloudWatchProgressSource


def main():
    arn = os.environ['AGENT_RUNTIME_ARN']
    profile = os.getenv('AWS_PROFILE', 'carecircle-admin')
    region = os.getenv('AWS_REGION', 'us-east-1')
    client = boto3.Session(profile_name=profile, region_name=region).client('logs')
    source = CloudWatchProgressSource(arn, region, profile, client=client)
    request = {'logGroupName': source.log_group, 'startTime': int((time() - 900) * 1000),
               'filterPattern': '"get_household_briefing"', 'limit': 100}
    invocations = []
    for _ in range(8):
        page = client.filter_log_events(**request)
        for item in page.get('events', []):
            try:
                event = json.loads(item['message'])
            except (KeyError, ValueError):
                continue
            if event.get('event') == 'mcp_tool_invoked' and event.get('tool') == 'get_household_briefing':
                invocations.append((item['timestamp'], event.get('session_id')))
        if not page.get('nextToken') or page['nextToken'] == request.get('nextToken'):
            break
        request['nextToken'] = page['nextToken']
    browser = [(timestamp, session) for timestamp, session in invocations
               if session and session.startswith('voice-') and session != 'voice-briefing-probe']
    if not browser:
        raise RuntimeError('NoRecentBrowserBriefingTrace')
    timestamp, session_id = max(browser)
    records = source.fetch(session_id, timestamp)
    completed = [x for x in records if x.get('event') == 'carecircle_progress' and x.get('status') == 'COMPLETE']
    print({'session_id': session_id, 'completed_agents': sorted({x['component'] for x in completed}),
           'completed_private_tools': sorted({x['operation'] for x in completed if x.get('kind') == 'tool'}),
           'triage_observed': any(x.get('component') == 'Triage Agent' for x in records),
           'create_incident_observed': any(x.get('operation') == 'create_incident' for x in records),
           'event_count': len(records)})


if __name__ == '__main__':
    main()
