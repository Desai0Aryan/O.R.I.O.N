"""The brain: one interface over several model providers."""
import os
import requests


class Brain:
    def __init__(self, cfg):
        self.cfg = cfg["brain"]
        provider = self.cfg.get("provider", "auto")
        if provider == "auto":
            provider = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "ollama"
        self.provider = provider

    def chat(self, system, messages):
        """messages: [{'role': 'user'|'assistant', 'content': str}, ...] -> str"""
        if self.provider == "anthropic":
            return self._anthropic(system, messages)
        if self.provider == "ollama":
            return self._ollama(system, messages)
        if self.provider == "openai_compatible":
            return self._openai(system, messages)
        raise ValueError(f"Unknown brain provider: {self.provider}")

    def _anthropic(self, system, messages):
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY missing. Put it in .env")
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.cfg["anthropic_model"],
                  "max_tokens": self.cfg.get("max_tokens", 1024),
                  "system": system, "messages": messages},
            timeout=120)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json()["content"])

    def _ollama(self, system, messages):
        r = requests.post(
            self.cfg["ollama_url"].rstrip("/") + "/api/chat",
            json={"model": self.cfg["ollama_model"], "stream": False,
                  "messages": [{"role": "system", "content": system}] + messages},
            timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _openai(self, system, messages):
        key = os.getenv("OPENAI_COMPAT_API_KEY", "")
        r = requests.post(
            self.cfg["openai_base_url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": self.cfg["openai_model"],
                  "max_tokens": self.cfg.get("max_tokens", 1024),
                  "messages": [{"role": "system", "content": system}] + messages},
            timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
