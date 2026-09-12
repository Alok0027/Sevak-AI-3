# SevakAI backend -- FastAPI + LangGraph.
#
# Built for a managed host (Render, Railway, Fly) rather than a laptop, so
# three things differ from `uvicorn app.main:app --reload`:
#
#   1. The port comes from the platform, not from us (see CMD).
#   2. faster-whisper is NOT installed. It is ~2GB of CTranslate2 and model
#      weights, it exceeds the free-tier build limits, and the server never
#      needs it: speech recognition in production is Bhashini's hosted API
#      (STT_PROVIDER=bhashini). Anyone wanting local Whisper installs
#      requirements-local-asr.txt on their own machine.
#   3. Nothing is copied from .env -- see .dockerignore.

FROM python:3.12-slim

# Byte-compiled .pyc files and buffered stdout are both wrong in a
# container: the first are noise in the layer, the second means a crash
# loop shows you an empty log because the traceback never flushed.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first, in their own layer. They change far less often than
# app code, so an ordinary code push reuses this layer instead of
# reinstalling LangGraph and SQLAlchemy every deploy.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user. A container that never needs to write outside
# /tmp has no reason to be able to.
RUN useradd --create-home --uid 1000 sevakai && chown -R sevakai:sevakai /app
USER sevakai

EXPOSE 8000

# Shell form, deliberately: $PORT has to be expanded at runtime. Managed
# hosts assign the port themselves and route to it; a container hardcoded
# to 8000 passes its own health check locally and is unreachable once
# deployed. The default keeps `docker run -p 8000:8000` working.
#
# No --reload (it watches the filesystem and doubles memory for nothing)
# and no --workers: these platforms scale by running more containers, and
# on a 512MB free instance a second worker is what gets you OOM-killed.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
