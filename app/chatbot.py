"""Target chatbot: answers staff questions with the fake handbook in context.

Context isolation design: the system prompt + handbook (hidden context) are
kept in dedicated attributes and are never part of the user-visible session
state. The mitigations toggle wraps the model call with input filtering,
hidden-context leak checking, output redaction, and safe sink encoding.
"""
import os

from .knowledge_base import HANDBOOK, SYSTEM_PROMPT
from .mitigations import (context_leak_check, encode_for_sink, input_filter,
                          redact_output)
from .models import get_model


class Chatbot:
    def __init__(self, cfg, base_dir):
        self.cfg = cfg
        self.model = get_model(cfg)
        self.events = []
        self.history = []
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)
        # Hidden context (LLM08): held server-side only.
        self._system = SYSTEM_PROMPT + "\n\nHANDBOOK CONTEXT:\n" + HANDBOOK

    def respond(self, user_text):
        if self.cfg.mitigations:
            hit = input_filter(user_text)
            if hit:
                self.events.append(f"input-filter: blocked (pattern '{hit}')")
                out = ("[BLOCKED] I can't follow instructions that override my "
                       "setup or ask for internal setup details.")
                self._write_sink(out)
                return out
        self.history.append({"role": "user", "content": user_text})
        context = {"mode": "chatbot", "raw_user": user_text}
        reply = self.model.generate(self._system, self.history, context)
        if self.cfg.mitigations:
            leak = context_leak_check(reply, self._system)
            if leak:
                self.events.append("context-isolation: hidden-context leak blocked")
                reply = "[BLOCKED] That response would expose internal setup details."
            reply, found = redact_output(reply)
            if found:
                self.events.append(f"output-redaction: redacted {found}")
        self.history.append({"role": "assistant", "content": reply})
        self._write_sink(reply)
        return reply

    def _write_sink(self, text):
        """Simulated downstream sink (LLM10): the answer is placed into an
        HTML page. Raw before mitigations, encoded after."""
        body = encode_for_sink(text) if self.cfg.mitigations else text
        with open(os.path.join(self.base_dir, "sink.html"), "w") as f:
            f.write(f"<html><body><div class='answer'>{body}</div></body></html>")

    def sink_content(self):
        path = os.path.join(self.base_dir, "sink.html")
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return ""
