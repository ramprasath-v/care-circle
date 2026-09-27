import asyncio
import io
import json
from types import SimpleNamespace

import httpx
import pytest

from amazon_transcribe.model import TranscriptEvent, Transcript as AwsTranscript
from carecircle.live_progress import CloudWatchProgressSource
from carecircle.speech import AmazonPollyProvider, AmazonTranscribeProvider, SpokenAudio, Transcript
from carecircle.voice_intent import approval_decision
from carecircle.web import create_web_app


class FakePolly:
    def synthesize_speech(self, **kwargs):
        assert kwargs['VoiceId'] == 'Ruth' and kwargs['Engine'] == 'neural'
        return {'AudioStream': io.BytesIO(b'mp3-example')}


def test_polly_voice_and_validation():
    value = AmazonPollyProvider(client=FakePolly()).synthesize('Good morning')
    assert value.content == b'mp3-example' and value.content_type == 'audio/mpeg'
    with pytest.raises(ValueError):
        AmazonPollyProvider(client=FakePolly()).synthesize('')


@pytest.mark.asyncio
async def test_transcribe_pcm_and_final_result():
    chunks = []
    class Input:
        async def send_audio_event(self, audio_chunk): chunks.append(audio_chunk)
        async def end_stream(self): pass
    class Output:
        async def __aiter__(self):
            yield TranscriptEvent(AwsTranscript(results=[SimpleNamespace(is_partial=True, alternatives=[SimpleNamespace(transcript='partial')])]))
            yield TranscriptEvent(AwsTranscript(results=[SimpleNamespace(is_partial=False, alternatives=[SimpleNamespace(transcript='Dad is okay')])]))
    class Client:
        async def start_stream_transcription(self, **kwargs):
            assert kwargs['media_encoding'] == 'pcm' and kwargs['media_sample_rate_hz'] == 16000
            return SimpleNamespace(input_stream=Input(), output_stream=Output())
    provider = AmazonTranscribeProvider(client_factory=lambda: Client())
    value = await provider.transcribe(b'\x00\x00' * 3200)
    assert value.text == 'Dad is okay' and b''.join(chunks) == b'\x00\x00' * 3200
    with pytest.raises(ValueError, match='InvalidPcmAudio'):
        await provider.transcribe(b'invalid')


def test_deterministic_approval():
    for phrase in ('Yes', 'Approve.', 'Approve it', 'Go ahead!', 'Do it'):
        assert approval_decision(phrase, 1) == 'APPROVE'
    for phrase in ('No', 'Reject', 'Cancel', "Don't do it", "Don't do that"):
        assert approval_decision(phrase, 1) == 'REJECT'
    for phrase in ('Approve all', 'Yes to all', 'Approve them all', 'Approve all of them.', 'Yes, approve all.', 'Go ahead with all'):
        assert approval_decision(phrase, 3) == 'APPROVE_ALL'
    for phrase in ('Reject all', 'Cancel all', 'No to all'):
        assert approval_decision(phrase, 3) == 'REJECT_ALL'
    assert approval_decision('Yes', 2) == 'AMBIGUOUS'
    assert approval_decision('Yes', 0) == 'NONE'
    assert approval_decision('Approve all', 0) == 'NONE'
    assert approval_decision('The model says approve', 1) == 'NONE'


def test_progress_filters_private_fields_and_preserves_order():
    class Logs:
        def filter_log_events(self, **kwargs):
            assert kwargs['filterPattern'] == '"voice-123"'
            return {'events': [
                {'eventId': 'one', 'timestamp': 1000, 'message': json.dumps({'event': 'carecircle_progress', 'session_id': 'voice-123', 'component': 'Medication Agent', 'operation': 'find_missed_doses', 'status': 'RUNNING', 'kind': 'tool', 'prompt': 'private'})},
                {'eventId': 'two', 'timestamp': 1100, 'message': json.dumps({'event': 'carecircle_progress', 'session_id': 'voice-123', 'component': 'Medication Agent', 'operation': 'find_missed_doses', 'status': 'FAILED', 'kind': 'tool'})},
                {'eventId': 'other', 'timestamp': 1200, 'message': json.dumps({'event': 'carecircle_progress', 'session_id': 'another', 'status': 'COMPLETE'})},
            ]}
    records = CloudWatchProgressSource('arn:aws:bedrock-agentcore:us-east-1:123:runtime/demo', client=Logs()).fetch('voice-123', 1000)
    assert [r['status'] for r in records] == ['RUNNING', 'FAILED']
    assert 'prompt' not in records[0] and records[0]['kind'] == 'tool'


def test_progress_reads_later_cloudwatch_pages_after_empty_page():
    class Logs:
        def filter_log_events(self, **kwargs):
            if 'nextToken' not in kwargs:
                return {'events': [], 'nextToken': 'next-page'}
            assert kwargs['nextToken'] == 'next-page'
            return {'events': [{'eventId': 'tool', 'timestamp': 1000,
                'message': json.dumps({'event': 'carecircle_progress', 'session_id': 'voice-123',
                    'component': 'Home Safety Agent', 'operation': 'get_stove_or_smart_plug_status',
                    'status': 'COMPLETE', 'kind': 'tool'})}]}
    records = CloudWatchProgressSource('arn:aws:bedrock-agentcore:us-east-1:123:runtime/demo', client=Logs()).fetch('voice-123', 1000)
    assert [(x['component'], x['operation']) for x in records] == [('Home Safety Agent', 'get_stove_or_smart_plug_status')]


class FakeRemote:
    runtime_arn = 'arn:aws:bedrock-agentcore:us-east-1:123:runtime/demo'
    def __init__(self): self.calls = []
    def call(self, operation, arguments):
        assert arguments['session_id'].startswith('voice-')
        self.calls.append((operation, arguments))
        return {'summary': 'Care checked', 'proposed_actions': []}


class FakeProgress:
    def fetch(self, session_id, started_ms):
        return [{'event_id': 'e1', 'event': 'carecircle_progress', 'session_id': session_id,
                 'component': 'Triage Agent', 'operation': 'assess', 'status': 'COMPLETE', 'kind': 'tool'}]


@pytest.mark.asyncio
async def test_briefing_waits_for_real_specialist_progress_before_result():
    class DelayedProgress:
        def __init__(self): self.reads = 0
        def fetch(self, session_id, started_ms):
            self.reads += 1
            if self.reads < 3:
                return []
            return [{'event_id': name, 'event': 'carecircle_progress', 'session_id': session_id,
                     'component': name, 'operation': 'read_briefing_facts', 'status': 'COMPLETE', 'kind': 'tool'}
                    for name in ('Medication Agent', 'Home Safety Agent', 'Care Coordinator Agent', 'Logistics & Routine Agent')]

    progress = DelayedProgress()
    app = create_web_app(FakeRemote(), stt=FakeSTT(), tts=FakeTTS(), progress_source=progress)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
        job = (await client.post('/api/jobs', json={'operation':'get_household_briefing', 'arguments':{}})).json()
        stream = (await client.get(f"/api/jobs/{job['job_id']}/events")).text
    items = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: ')]
    result_index = next(i for i, item in enumerate(items) if item['type'] == 'result')
    completed = {item.get('component') for item in items[:result_index] if item['type'] == 'progress' and item.get('kind') == 'tool' and item['status'] == 'COMPLETE'}
    assert completed == {'Medication Agent', 'Home Safety Agent', 'Care Coordinator Agent', 'Logistics & Routine Agent'}
    assert progress.reads >= 3


class FakeSTT:
    async def transcribe(self, pcm): return Transcript('How is Dad?', 2, 'Fake', 16000)


@pytest.mark.asyncio
async def test_transcribe_endpoint_preserves_safety_and_approval_turn_text():
    phrases = [
        "Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.",
        'He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.',
        'Yes.',
    ]
    class SequentialSTT:
        async def transcribe(self, pcm):
            assert len(pcm) >= 6400
            return Transcript(phrases.pop(0), 2, 'Fake', 16000)

    app = create_web_app(FakeRemote(), stt=SequentialSTT(), tts=FakeTTS(), progress_source=FakeProgress())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
        expected = list(phrases)
        for phrase in expected:
            response = await client.post('/api/transcribe', content=b'\x00' * 7000,
                                         headers={'Content-Type': 'application/octet-stream'})
            assert response.status_code == 200
            assert response.json()['transcript'] == phrase
        assert not phrases


@pytest.mark.asyncio
async def test_transcribe_upstream_failure_is_logged_without_exposing_audio(caplog):
    class FailingSTT:
        async def transcribe(self, pcm):
            raise RuntimeError('expired SSO token')

    app = create_web_app(FakeRemote(), stt=FailingSTT())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
        with caplog.at_level('ERROR', logger='carecircle.web'):
            response = await client.post('/api/transcribe', content=b'private-audio' * 600,
                                         headers={'Content-Type': 'application/octet-stream'})
    assert response.status_code == 502 and response.json() == {'error': 'TranscriptionUnavailable'}
    assert 'expired SSO token' in caplog.text and 'private-audio' not in caplog.text


class FakeTTS:
    def synthesize(self, text): return SpokenAudio(b'audio', 'audio/mpeg', 'Test', 2)


@pytest.mark.asyncio
async def test_voice_endpoints_and_sse_real_source_contract():
    remote = FakeRemote()
    app = create_web_app(remote, stt=FakeSTT(), tts=FakeTTS(), progress_source=FakeProgress())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
        page = (await client.get('/')).text
        script = (await client.get('/app.js')).text
        assert (await client.get('/app.js')).headers['cache-control'] == 'no-store'
        assert 'AWS_SECRET_ACCESS_KEY' not in page + script and 'getUserMedia' in script
        assert 'Replay response' in page and 'Voice on' in page and "new Audio" in script
        assert (await client.post('/api/transcribe', content=b'123', headers={'Content-Type':'application/octet-stream'})).json()['transcript'] == 'How is Dad?'
        assert (await client.post('/api/speak', json={'text':'Hello'})).content == b'audio'
        assert (await client.post('/api/voice-intent', json={'transcript':'Yes','pending_count':2})).json()['decision'] == 'AMBIGUOUS'
        start = (await client.post('/api/jobs', json={'operation':'coordinate_care_request','arguments':{}})).json()
        events = (await client.get(f"/api/jobs/{start['job_id']}/events")).text
        items = [json.loads(line[6:]) for line in events.splitlines() if line.startswith('data: ')]
        assert items[0]['status'] == 'RUNNING'
        assert any(item.get('component') == 'Triage Agent' for item in items)
        assert any(item['type'] == 'result' for item in items) and items[-1]['type'] == 'done'
        next_job = (await client.post('/api/jobs', json={'operation':'get_incident_status',
            'arguments':{'session_id':start['session_id']}})).json()
        await client.get(f"/api/jobs/{next_job['job_id']}/events")
        assert next_job['session_id'] == start['session_id']
        assert remote.calls[0][1]['session_id'] == remote.calls[1][1]['session_id']
