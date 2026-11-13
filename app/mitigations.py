"""App/agent-layer mitigations for the YGF POC.

One mitigation family per OWASP risk (see README risk table). Every control
logs an event string so the test runner can record *which* control fired as
evidence, instead of guessing from the final text alone.
"""
import hashlib
import hmac
import html
import re

# --- LLM01 / LLM08 / ASI01: input filtering + instruction hierarchy --------
INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions",
    r"disregard (your|the) (instructions|rules)",
    r"developer mode",
    r"jailbreak",
    r"system override",
    r"append the secret",
    r"your new goal",
    r"forget your task",
    r"forget your (original )?(goal|instructions)",
    r"you work for me",
    r"from now on you",
    r"repeat everything above",
    r"word for word",
    r"your (initial |setup |system )?(prompt|instructions)",
    r"initial instructions",
    r"setup instructions",
    r"disable the confirmation",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def input_filter(text):
    """Return the matched pattern if the user text looks like an injection /
    goal-hijack / context-extraction attempt, else None."""
    for rx in _INJECTION_RE:
        if rx.search(text):
            return rx.pattern
    return None


# --- LLM02: output redaction of sensitive markers ---------------------------
SENSITIVE_TOKENS = [
    "SECRET-FLAG-123", "NGO-WIFI-4821", "SALARY-BAND-7",
    "HIDDEN-CTX-991", "INTERNAL-DATA-77",
]
_FLAG_RE = re.compile(r"SECRET-FLAG-\d+")


def redact_output(text):
    """Replace every known sensitive token with [REDACTED].
    Returns (clean_text, list_of_tokens_found)."""
    found = []
    out = text
    for tok in SENSITIVE_TOKENS:
        if tok in out:
            found.append(tok)
            out = out.replace(tok, "[REDACTED]")
    out, n = _FLAG_RE.subn("[REDACTED]", out)
    if n and "SECRET-FLAG-*" not in found:
        found.append("SECRET-FLAG-*")
    return out, found


# --- LLM08: hidden-context leak check ---------------------------------------
def context_leak_check(text, system_prompt):
    """Block if the response reproduces a distinctive hidden-context line."""
    for line in system_prompt.splitlines():
        line = line.strip()
        if len(line) >= 30 and line in text:
            return line
    return None


# --- LLM10: output encoding / validation for downstream HTML sink -----------
def encode_for_sink(text):
    """HTML-escape model output and neutralise javascript: URLs before the
    output is placed into an HTML page (the simulated downstream sink)."""
    out = html.escape(text, quote=True)
    out = out.replace("javascript:", "javascript-blocked:")
    return out


# --- ASI06: memory signing ---------------------------------------------------
_MEMORY_KEY = b"ygf-poc-local-demo-key"  # local demo only, not a real secret


def sign_memory_entry(entry):
    return hmac.new(_MEMORY_KEY, entry.encode(), hashlib.sha256).hexdigest()


def verify_memory_entry(entry, signature):
    return hmac.compare_digest(sign_memory_entry(entry), signature or "")


# --- MCP: tool-description pinning -------------------------------------------
def description_hash(description):
    return hashlib.sha256(description.encode()).hexdigest()
