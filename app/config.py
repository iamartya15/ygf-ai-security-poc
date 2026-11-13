"""Configuration for the YGF POC target app.

Flags can be set via constructor arguments (the test runner does this) or
environment variables:
  MODEL=gemini|claude|mock      (default: mock)
  MITIGATIONS=on|off            (default: off)
API keys are read ONLY from the environment (GEMINI_API_KEY,
ANTHROPIC_API_KEY) and are never stored in any file.
"""
import os


class NoKeyError(Exception):
    """Raised when a real model is requested but its API key is absent."""


class Config:
    def __init__(self, model=None, mitigations=None, session_role="public"):
        self.model = (model or os.environ.get("MODEL", "mock")).lower()
        if mitigations is None:
            mitigations = os.environ.get("MITIGATIONS", "off").lower() == "on"
        self.mitigations = bool(mitigations)
        # Trusted identity channel: the caller's role comes from the hosting
        # application (this constructor), NEVER from user-supplied text.
        self.session_role = session_role
        self.gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        self.anthropic_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")

    @property
    def phase(self):
        return "After" if self.mitigations else "Before"
