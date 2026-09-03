"""
Test-suite-wide setup.

Forces safe, network-free settings regardless of whatever the developer's
local .env has (e.g. STT_PROVIDER=whisper for a live demo would otherwise
make every test run try to download Whisper model weights over the
network). This must execute before any test module imports the app, so
pydantic-settings picks up these env vars ahead of get_settings()'s first
call and its own .env file read.
"""
import os

os.environ["STT_PROVIDER"] = "mock"
os.environ["USE_MOCKS"] = "true"
