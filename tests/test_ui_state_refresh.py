"""Run the browser script against a deterministic MCP/SSE and DOM boundary."""
import shutil
import subprocess
import os
import asyncio
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from carecircle.speech import Transcript
from carecircle.web import create_web_app


def test_persisted_state_refreshes_after_mutations_without_repeating_actions():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available for the browser behavior test")
    script = Path(__file__).with_name("ui_state_refresh.cjs")
    subprocess.run([node, str(script)], check=True, timeout=15)


def test_transcribed_microphone_turns_match_typed_session_and_state():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available for the browser behavior test")
    script = Path(__file__).with_name("ui_state_refresh.cjs")
    subprocess.run([node, str(script)], check=True, timeout=15,
                   env={**os.environ, "CARE_MIC_TEST": "1"})


def test_microphone_recorder_uses_real_transcribe_endpoint_and_shared_turn_handler():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not available for the browser behavior test")
    utterances = iter([
        "Dad just called and seems confused and isn't sure whether he took his medication. Please coordinate help.",
        "He is awake and responsive. No chest pain, no trouble breathing, and no trouble speaking. The confusion is new.",
        "Yes.",
    ])

    class SimulatedTranscribe:
        async def transcribe(self, pcm):
            assert len(pcm) >= 6400
            return Transcript(next(utterances), 1, "simulated-transcribe", 16000)

    app = create_web_app(remote=object(), stt=SimulatedTranscribe())
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", 0))
    except PermissionError:
        sock.close()
        pytest.skip("This sandbox does not allow a loopback test server")
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[sock])), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.02)
        assert server.started
        script = Path(__file__).with_name("ui_state_refresh.cjs")
        subprocess.run([node, str(script)], check=True, timeout=15,
                       env={**os.environ, "CARE_MIC_TEST": "1", "CARE_MIC_ONLY": "1",
                            "CARE_TRANSCRIBE_URL": f"http://127.0.0.1:{port}/api/transcribe"})
        assert next(utterances, None) is None
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
