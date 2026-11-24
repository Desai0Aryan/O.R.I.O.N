"""The brain: one interface over several model providers, with retries and fallback."""
import os
import time

import requests


class BrainError(RuntimeError):
    pass


def anthropic_messages(messages):
    """Our messages may carry 'images': [{'media_type','data'}]; Anthropic wants content blocks."""
    out = []
    for m in messages:
        imgs = m.get("images") or []
        if imgs:
            blocks = [{"type": "image", "source": {"type": "base64", "media_type": i["media_type"], "data": i["data"]}}
                      for i in imgs]
            blocks.append({"type": "text", "text": m["content"] or "(see the attached image)"})
            out.append({"role": m["role"], "content": blocks})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def ollama_messages(messages):
    out = []
    for m in messages:
        d = {"role": m["role"], "content": m["content"]}
        if m.get("images"):
            d["images"] = [i["data"] for i in m["images"]]
        out.append(d)
    return out


def openai_messages(messages):
    out = []
    for m in messages:
        imgs = m.get("images") or []
        if imgs:
            parts = [{"type": "text", "text": m["content"] or "(see the attached image)"}]
            parts += [{"type": "image_url", "image_url": {"url": f"data:{i['media_type']};base64,{i['data']}"}}
                      for i in imgs]
            out.append({"role": m["role"], "content": parts})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _describe(e):
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    return f"{type(e).__name__}: {e}"


class Brain:
    def __init__(self, cfg):
        self.cfg = cfg["brain"]
        p = self.cfg.get("provider", "auto")
        if p == "auto":
            p = "anthropic" if os.getenv("ANTHROPIC_API_KEY") else "ollama"
        self.provider = p
        self.chain = [p] + [x for x in (self.cfg.get("fallback") or []) if x != p]
        self.last_used = p

    def chat(self, system, messages, task="main", json_mode=False, max_tokens=None, retries=None):
        """messages: [{'role': 'user'|'assistant', 'content': str}] -> reply text.
        task='fast' uses the cheaper model for memory upkeep."""
        retries = int(self.cfg.get("retries", 2)) if retries is None else retries
        errors = []
        for prov in self.chain:
            for attempt in range(retries + 1):
                try:
                    out = self._call(prov, system, messages, task, json_mode, max_tokens)
                    self.last_used = prov
                    return out
                except requests.HTTPError as e:
                    errors.append(f"{prov}: {_describe(e)}")
                    status = e.response.status_code if e.response is not None else 0
                    if status in (400, 401, 403, 404):
                        break
                    time.sleep(1.5 * (attempt + 1))
                except (requests.ConnectionError, requests.Timeout) as e:
                    errors.append(f"{prov}: {_describe(e)}")
                    time.sleep(1.0 * (attempt + 1))
                except Exception as e:
                    errors.append(f"{prov}: {_describe(e)}")
                    break
        raise BrainError("; ".join(errors[-3:]) or "no brain configured")

    def _model(self, prov, task):
        key = {"anthropic": "anthropic", "ollama": "ollama", "openai_compatible": "openai"}[prov]
        fast = self.cfg.get(f"{key}_fast_model")
        return fast if (task == "fast" and fast) else self.cfg[f"{key}_model"]

    def _call(self, prov, system, messages, task, json_mode, max_tokens):
        mt = max_tokens or self.cfg.get("max_tokens", 1200)
        temp = self.cfg.get("temperature")
        model = self._model(prov, task)
        if prov == "anthropic":
            key = os.getenv("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("ANTHROPIC_API_KEY is missing (put it in .env)")
            body = {"model": model, "max_tokens": mt, "system": system, "messages": anthropic_messages(messages)}
            if temp is not None:
                body["temperature"] = temp
            r = requests.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"}, json=body, timeout=120)
            r.raise_for_status()
            return "".join(b.get("text", "") for b in r.json()["content"])
        if prov == "ollama":
            body = {"model": model, "stream": False, "keep_alive": "30m",
                    "messages": [{"role": "system", "content": system}] + ollama_messages(messages),
                    "options": {"num_predict": mt}}
            if temp is not None:
                body["options"]["temperature"] = temp
            if json_mode:
                body["format"] = "json"
            r = requests.post(self.cfg["ollama_url"].rstrip("/") + "/api/chat", json=body, timeout=300)
            r.raise_for_status()
            return r.json()["message"]["content"]
        if prov == "openai_compatible":
            body = {"model": model, "max_tokens": mt,
                    "messages": [{"role": "system", "content": system}] + openai_messages(messages)}
            if temp is not None:
                body["temperature"] = temp
            r = requests.post(self.cfg["openai_base_url"].rstrip("/") + "/chat/completions",
                              headers={"Authorization": f"Bearer {os.getenv('OPENAI_COMPAT_API_KEY', '')}"},
                              json=body, timeout=120)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        raise ValueError(f"Unknown brain provider: {prov}")
