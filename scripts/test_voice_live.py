"""Live Amazon Polly -> Amazon Transcribe check without requiring microphone hardware."""
import asyncio
import json
import os
from time import perf_counter

import boto3
import httpx

from carecircle.speech import AmazonPollyProvider, AmazonTranscribeProvider
from carecircle.schemas import HouseholdBriefing
from carecircle.web import create_web_app


async def main():
    profile = os.getenv('AWS_PROFILE', 'carecircle-admin')
    region = os.getenv('AWS_REGION', 'us-east-1')
    session = boto3.Session(profile_name=profile, region_name=region)
    polly = session.client('polly')
    started = perf_counter()
    response = polly.synthesize_speech(Text='How is Dad doing this morning?', TextType='text',
                                       VoiceId='Ruth', Engine='neural', OutputFormat='pcm', SampleRate='16000')
    with response['AudioStream'] as stream:
        pcm = stream.read()
    transcript = await AmazonTranscribeProvider(region, profile).transcribe(pcm)
    speech = AmazonPollyProvider(region, profile).synthesize('CareCircle is ready to coordinate care.')
    print({'transcript': transcript.text, 'transcribe_provider': transcript.provider,
           'transcribe_latency_ms': transcript.latency_ms, 'polly_bytes': len(speech.content),
           'polly_voice': speech.voice, 'end_to_end_ms': round((perf_counter()-started)*1000)})
    if 'dad' not in transcript.text.lower():
        raise RuntimeError('Unexpected live transcript')
    if not os.getenv('AGENT_RUNTIME_ARN'):
        print('Set AGENT_RUNTIME_ARN to include the authenticated web-to-AgentCore loop.')
        return
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_web_app()),
                                 base_url='http://localhost', timeout=180) as web:
        transcribed = await web.post('/api/transcribe', content=pcm,
                                    headers={'Content-Type':'application/octet-stream'})
        transcribed.raise_for_status()
        spoken_text = transcribed.json()['transcript']
        if 'dad' not in spoken_text.lower():
            raise AssertionError('Web Transcribe endpoint lost the utterance')
        started_job = await web.post('/api/jobs', json={'operation':'get_household_briefing',
                                                        'arguments':{'household_id':'demo-household'}})
        started_job.raise_for_status()
        stream = await web.get(f"/api/jobs/{started_job.json()['job_id']}/events")
        stream.raise_for_status()
        events = [json.loads(line[6:]) for line in stream.text.splitlines() if line.startswith('data: ')]
        results = [item for item in events if item['type'] == 'result']
        if not results:
            raise RuntimeError('Live voice request did not return a briefing')
        briefing = HouseholdBriefing.model_validate(results[0]['value'])
        reply = f"CareCircle checked the household. There are {len(briefing.open_care_tasks)} open care tasks."
        audio = await web.post('/api/speak', json={'text':reply})
        audio.raise_for_status()
        print({'web_transcript':spoken_text,'mcp_tool':'get_household_briefing',
               'observed_progress_events':sum(item['type']=='progress' for item in events),
               'spoken_reply_bytes':len(audio.content),'total_web_latency_ms':round((perf_counter()-started)*1000)})


if __name__ == '__main__':
    asyncio.run(main())
