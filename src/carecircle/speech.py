"""Server-side Amazon speech adapters; audio and AWS credentials never enter logs."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Protocol


@dataclass(frozen=True)
class Transcript:
    text: str
    latency_ms: float
    provider: str
    sample_rate_hz: int


@dataclass(frozen=True)
class SpokenAudio:
    content: bytes
    content_type: str
    voice: str
    latency_ms: float


class SpeechToTextProvider(Protocol):
    async def transcribe(self, pcm: bytes, sample_rate_hz: int = 16000) -> Transcript: ...


class TextToSpeechProvider(Protocol):
    def synthesize(self, text: str) -> SpokenAudio: ...


class AmazonTranscribeProvider:
    """Stream one short, recorded 16-bit mono PCM clip at its natural byte rate."""

    def __init__(self, region: str = "us-east-1", profile: str | None = None,
                 client_factory: Any = None):
        self.region, self.profile, self.client_factory = region, profile, client_factory

    def _client(self):
        if self.client_factory:
            return self.client_factory()
        import boto3
        from amazon_transcribe.auth import StaticCredentialResolver
        from amazon_transcribe.client import TranscribeStreamingClient

        credentials = boto3.Session(profile_name=self.profile, region_name=self.region).get_credentials()
        if credentials is None:
            raise RuntimeError("AwsCredentialsUnavailable")
        frozen = credentials.get_frozen_credentials()
        resolver = StaticCredentialResolver(frozen.access_key, frozen.secret_key, frozen.token)
        return TranscribeStreamingClient(region=self.region, credential_resolver=resolver)

    async def transcribe(self, pcm: bytes, sample_rate_hz: int = 16000) -> Transcript:
        if sample_rate_hz != 16000 or len(pcm) < 6400 or len(pcm) > 640000 or len(pcm) % 2:
            raise ValueError("InvalidPcmAudio")
        from amazon_transcribe.handlers import TranscriptResultStreamHandler

        started = perf_counter()
        client = self._client()
        stream = await client.start_stream_transcription(
            language_code="en-US", media_sample_rate_hz=sample_rate_hz, media_encoding="pcm",
        )
        final_parts: list[str] = []

        class Collector(TranscriptResultStreamHandler):
            async def handle_transcript_event(self, event):
                for result in event.transcript.results:
                    if not result.is_partial and result.alternatives:
                        final_parts.append(result.alternatives[0].transcript)

        async def write_audio():
            # 100 ms chunks; pacing avoids overwhelming Transcribe with a pre-recorded clip.
            for offset in range(0, len(pcm), 3200):
                chunk = pcm[offset:offset + 3200]
                await stream.input_stream.send_audio_event(audio_chunk=chunk)
                await asyncio.sleep(len(chunk) / (sample_rate_hz * 2))
            await stream.input_stream.end_stream()

        await asyncio.wait_for(asyncio.gather(write_audio(), Collector(stream.output_stream).handle_events()), timeout=35)
        text = " ".join(final_parts).strip()
        if not text:
            raise ValueError("NoSpeechDetected")
        return Transcript(text, round((perf_counter() - started) * 1000, 2), "Amazon Transcribe", sample_rate_hz)


class AmazonPollyProvider:
    def __init__(self, region: str = "us-east-1", profile: str | None = None, client: Any = None):
        if client is None:
            import boto3
            client = boto3.Session(profile_name=profile, region_name=region).client("polly")
        self.client = client

    def synthesize(self, text: str) -> SpokenAudio:
        if not text or len(text) > 1500:
            raise ValueError("InvalidSpeechText")
        started = perf_counter()
        response = self.client.synthesize_speech(
            Text=text, TextType="text", OutputFormat="mp3", VoiceId="Ruth", Engine="neural",
        )
        with response["AudioStream"] as stream:
            content = stream.read()
        if not content:
            raise RuntimeError("EmptyPollyAudio")
        return SpokenAudio(content, "audio/mpeg", "Ruth (CareCircle voice)", round((perf_counter() - started) * 1000, 2))
