"""
config.py — central configuration and constants
- Reads from Streamlit secrets (if available) or environment variables
- Provides DB URL, Graph credentials, mailbox/folder, and notification mode
"""

import os

# Try to load Streamlit secrets if available (agent.py does not depend on Streamlit)
try:
    import streamlit as st
    _SECRETS = getattr(st, "secrets", {})
except Exception:
    _SECRETS = {}

def _get(key: str, default: str = "") -> str:
    # Priority: Streamlit secrets -> env var -> default
    if _SECRETS and key in _SECRETS:
        return str(_SECRETS.get(key, default))
    return str(os.getenv(key, default))

# --- Database ---
DEFAULT_DB = "sqlite:///regtracker.db"
DATABASE_URL = _get("DATABASE_URL", DEFAULT_DB)

# --- Microsoft Graph / Entra ID (application permissions) ---
GRAPH_TENANT_ID    = _get("GRAPH_TENANT_ID", "")
GRAPH_CLIENT_ID    = _get("GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET= _get("GRAPH_CLIENT_SECRET", "")

# --- Mailbox and folder settings ---
GRAPH_MAILBOX          = _get("GRAPH_MAILBOX", "d.banerjee@reederei-nord.nl")
GRAPH_PARENT_FOLDER    = _get("GRAPH_PARENT_FOLDER", "inbox")       # well-known name
GRAPH_TARGET_SUBFOLDER = _get("GRAPH_TARGET_SUBFOLDER", "Regulations")

# --- Notifications ---
NOTIFY_MODE = _get("NOTIFY_MODE", "disabled")  # "disabled" or "email"
DEFAULT_NOTIFY = [GRAPH_MAILBOX]               # fallback: notify self

# --- OpenAI extraction ---
OPENAI_API_KEY = _get("OPENAI_API_KEY", "")
OPENAI_MODEL = _get("OPENAI_MODEL", "gpt-4o-mini")

# Department mapping (fill with real distro lists later)
DEPT_NOTIFY = {
    # "Marine Ops": ["operations@reederei-nord.nl"],
    # "Technical": ["tech@reederei-nord.nl"],
    # "HSEQ": ["hseq@reederei-nord.nl"],
    # "Crewing": ["crewing@reederei-nord.nl"],
    # "Human Resourses": ["hr@reederei-nord.nl"],  # keep spelling to match UI constants
}

# Keyword routing (optional, extend later)
KEYWORD_NOTIFY = {
    # "MARPOL": ["hseq@reederei-nord.nl", "operations@reederei-nord.nl"],
    # "MRV": ["hseq@reederei-nord.nl"],
    # "USCG": ["operations@reederei-nord.nl"],
    # "IMO": ["technical@reederei-nord.nl", "hseq@reederei-nord.nl"],
}

# Sender routing (optional)
SENDER_NOTIFY = {
    # "orchid@reederei-nord.net": ["operations@reederei-nord.nl"],
}

# --- UI constants (share with models/helpers) ---
DEPARTMENTS = ["Crewing", "Marine Ops", "Technical", "Human Resourses", "HSEQ"]  # requested spelling
REG_STATUS_OPTIONS = ["Open", "In Progress", "Closed", "N/A"]
