"""
backend/config.py — Configuration, API Keys & Secret Setup

It reads secret keys from the `.env` file, connects to the AI provider (Groq),
and sets up the activity tracker (Langfuse).
All other files simply import from here so we don't repeat settings everywhere.
"""
# 1. SSL Certificate Fix:
# Some Windows environments or corporate networks have issues verifying HTTPS certificates.
# Truststore automatically uses Windows' native certificate vault so API calls don't fail with SSL errors.
import truststore
truststore.inject_into_ssl()

import os
from dotenv import load_dotenv
from groq import Groq
from langfuse import Langfuse

# 2. Find and load the `.env` file from the main project root folder
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ── 3. Groq AI Connections (Primary + Backup) ─────────────────────────────────
# We pull our Groq API keys here. Stripping extra whitespace or stray quotes.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip().strip("\"'")
GROQ_API_KEY_FALLBACK = os.environ.get("GROQ_API_KEY_FALLBACK", "").strip().strip("\"'")

# If the primary key is missing, stop immediately and warn the user.
if not GROQ_API_KEY:
    raise SystemExit("GROQ_API_KEY is not set. Add it to .env and restart.")

# Set up two clients:
# Primary client: Used for normal operation.
# Fallback client: A backup key/account used automatically if the primary runs into a rate limit!
client_primary = Groq(api_key=GROQ_API_KEY)
client_fallback = Groq(api_key=GROQ_API_KEY_FALLBACK or GROQ_API_KEY)

# Which AI models to use:
# If the primary model fails or is busy, the app smoothly switches to the fallback model.
PRIMARY_MODEL = os.environ.get("PRIMARY_MODEL", "openai/gpt-oss-120b").strip()
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "qwen/qwen3.8-27b").strip()

# Safety limits to avoid sending too much text to the AI at once
MAX_HISTORY_MESSAGES = 40  # Keep only the latest 40 messages to avoid overloading context
MAX_MESSAGE_CHARS = 4000   # Prevent someone from pasting an entire book into the chat

# ── 4. Langfuse Observability (Our Flight Recorder) ────────────────────────────
# Langfuse tracks AI responses, speed, token usage, and alerts if contradictions happen.
LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "").strip().strip("\"'")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip().strip("\"'")
LANGFUSE_BASE_URL = os.environ.get("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com").strip().strip("\"'")

langfuse: Langfuse | None = None
LANGFUSE_ENABLED = False

# Only connect if the keys were actually provided in `.env`
if LANGFUSE_SECRET_KEY and LANGFUSE_PUBLIC_KEY:
    try:
        langfuse = Langfuse(
            secret_key=LANGFUSE_SECRET_KEY,
            public_key=LANGFUSE_PUBLIC_KEY,
            host=LANGFUSE_BASE_URL,
        )
        # Check if the keys are valid and the cloud server responds
        LANGFUSE_ENABLED = langfuse.auth_check()
        if LANGFUSE_ENABLED:
            print(f"[Langfuse] Connected to {LANGFUSE_BASE_URL}")
        else:
            print("[Langfuse] auth_check failed — tracing disabled.")
    except Exception as _lf_err:
        print(f"[Langfuse] Init error: {_lf_err} — tracing disabled.")
        langfuse = None
