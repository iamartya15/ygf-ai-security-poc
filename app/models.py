"""Model backends: mock (deterministic local stand-in), Gemini, Claude,
NVIDIA NIM (an open-weights model served over NVIDIA's free
OpenAI-compatible endpoint).

The REAL backends call the providers' HTTPS APIs with keys taken only from
the environment. The mock is NOT an LLM and its results must never be
presented as real-model results - it is a rule-based stand-in that
simulates how a *vulnerable* instruction-following model behaves, so the
app-layer mitigations can be smoke-tested end-to-end without any API key.
"""
import json
import os
import re
import time

import requests


def _post_with_retry(url, **kwargs):
    """POST with backoff on transient provider errors (429/5xx/timeouts).

    Free-tier APIs rate-limit aggressively; a live test suite must ride
    out those limits instead of recording them as test outcomes.
    """
    delay = 15
    last_exc = None
    for attempt in range(7):
        try:
            r = requests.post(url, **kwargs)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 6:
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc
            if attempt >= 6:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 120)
    if last_exc:
        raise last_exc
    return r

from .config import NoKeyError
from .knowledge_base import FLAG, HANDBOOK, PUBLIC_INFO


class MockModel:
    """Deterministic rule-based stand-in. Labelled MOCK everywhere.

    Behaviour contract (this simulates the *model's* weaknesses; the
    mitigations live in the app/agent layer, not here):
    - Chatbot mode: questions that reference handbook/secret/system content
      cause it to regurgitate its context (handbook or system prompt).
    - Agent mode: natural-language tool directives are converted into a
      TOOL_CALL line; goal-change directives are 'accepted'.
    - With an observation (tool result), it formats the result as its answer,
      and if the connected MCP tool description was poisoned and went
      unverified, it also appends handbook content (simulating a model that
      followed the poisoned tool description).
    - Memory: planted claims present in *stored* memory are echoed back and
      acted on; claims the app refused to store are absent, so they are not.
    """
    name = "mock"

    def generate(self, system, messages, context):
        last = messages[-1]["content"] if messages else ""
        low = last.lower()
        mode = context.get("mode", "chatbot")
        observation = context.get("observation")

        if observation is not None:
            answer = f"Here is the result: {observation}"
            if context.get("mcp_poison_active"):
                answer += "\nAdditional context from the handbook: " + HANDBOOK
            return answer

        if mode == "agent":
            return self._agent_reply(low, last, messages, context)
        return self._chatbot_reply(low, system, context)

    # -- chatbot persona -----------------------------------------------------
    def _chatbot_reply(self, low, system, context):
        # Raw-HTML / script echo requests: a naive model complies verbatim.
        for marker in ("<script", "<img", "javascript:"):
            if marker in low:
                idx = low.find(marker)
                return "Here you go: " + context["raw_user"][idx:]
        # Handbook / secret regurgitation.
        if "handbook" in low or "salary" in low or "wi-fi" in low or "wifi" in low:
            return "From the handbook in my context:\n" + HANDBOOK
        if "flag" in low or "secret" in low:
            return f"The verification marker in my context is {FLAG}."
        # Hidden-context extraction.
        if any(p in low for p in ("system prompt", "instructions", "everything above",
                                  "told about", "debugging")):
            return "My setup text is:\n" + system
        return "I can help with public information. " + PUBLIC_INFO

    # -- agent persona ---------------------------------------------------------
    def _agent_reply(self, low, raw, messages, context):
        memory = context.get("memory", [])
        probe = ("you remember" in low or "per the" in low
                 or "using what you remember" in low)
        # Memory exploitation probes (only when a later turn leans on the
        # planted memory; the planting turn itself gets a neutral reply).
        if memory and probe and ("director" in low or "approval" in low) \
                and ("flag" in low or "approv" in low):
            fact = memory[0]
            return (f"Based on what I remember: {fact}. "
                    f"The verification marker is {FLAG}.")
        if memory and probe and "salary" in low:
            return ("Based on what I remember about the salary data: the "
                    "coordinator stipend reference is SALARY-BAND-7.")
        # Tool directives.
        call = self._parse_tool_call(low, raw)
        if call:
            return "TOOL_CALL: " + json.dumps(call)
        # Goal hijack acceptance.
        if any(p in low for p in ("new goal", "work for me", "forget your task",
                                  "your only job", "from now on you")):
            return "GOAL-CHANGED: I have adopted the new goal you gave me."
        return "I can retrieve public files and draft communications for staff."

    def _parse_tool_call(self, low, raw):
        # Code blocks first: payload code may itself mention files/open().
        m = re.search(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
        if ("run code" in low or "execute" in low) and m:
            return {"tool": "run_code", "args": {"code": m.group(1)}}
        m = re.search(r"([\w.\-]+\.txt)", low)
        if ("read" in low or "open" in low) and m:
            return {"tool": "read_file", "args": {"path": m.group(1)}}
        m = re.search(r"[\w.\-]+@[\w.\-]+", raw)
        if ("send_email" in low or "email" in low) and m:
            body = "the handbook contents (SECRET-FLAG-123)" if "handbook" in low else "the grant is approved"
            return {"tool": "send_email", "args": {"to": m.group(0),
                                                    "subject": "YGF update",
                                                    "body": body}}
        m = re.search(r"https?://\S+", raw)
        if ("http_call" in low or "fetch" in low or "post" in low) and m:
            return {"tool": "http_call", "args": {"url": m.group(0).rstrip(".,)"),
                                                   "payload": "handbook contents SECRET-FLAG-123"}}
        return None


class GeminiModel:
    name = "gemini"

    def __init__(self, cfg):
        self.key = os.environ.get("GEMINI_API_KEY")
        if not self.key:
            raise NoKeyError("GEMINI_API_KEY not set in environment")
        self.model = cfg.gemini_model

    def generate(self, system, messages, context):
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent?key={self.key}")
        contents = [{"role": "user" if m["role"] == "user" else "model",
                     "parts": [{"text": m["content"]}]} for m in messages]
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": contents}
        r = _post_with_retry(url, json=body, timeout=60)
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]


class ClaudeModel:
    name = "claude"

    def __init__(self, cfg):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise NoKeyError("ANTHROPIC_API_KEY not set in environment")
        self.model = cfg.anthropic_model

    def generate(self, system, messages, context):
        r = _post_with_retry(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": self.key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.model, "max_tokens": 1024, "system": system,
                  "messages": messages},
            timeout=60)
        r.raise_for_status()
        data = r.json()
        return "".join(b.get("text", "") for b in data["content"])


class NvidiaModel:
    """A real open-weights model via NVIDIA NIM's free endpoint.

    NIM's chat API is OpenAI-compatible. The default model is Mistral
    Large 4 (`mistralai/mistral-large-4-1t-a52b`, from cfg.nvidia_model);
    the model id is configurable via the NVIDIA_MODEL environment
    variable, since NIM retires catalog ids over time (the originally
    planned Llama 3.3 70B id returned HTTP 410 Gone on 2026-11-13).
    Runs against this backend are a genuinely different model family
    from Gemini and Claude - and must be labelled as what they are
    (NVIDIA / the actual model id), never as Claude.
    """
    name = "nvidia"

    def __init__(self, cfg):
        self.key = os.environ.get("NVIDIA_API_KEY")
        if not self.key:
            raise NoKeyError("NVIDIA_API_KEY not set in environment")
        self.model = cfg.nvidia_model

    def generate(self, system, messages, context):
        r = _post_with_retry(
            "https://integrate.api.nvidia.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.key}",
                     "content-type": "application/json"},
            json={"model": self.model,
                  "messages": ([{"role": "system", "content": system}]
                               + messages),
                  "max_tokens": 1024},
            timeout=60)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


def get_model(cfg):
    if cfg.model == "gemini":
        return GeminiModel(cfg)
    if cfg.model == "claude":
        return ClaudeModel(cfg)
    if cfg.model == "nvidia":
        return NvidiaModel(cfg)
    return MockModel()
