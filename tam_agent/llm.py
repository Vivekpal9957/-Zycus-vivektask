"""LLM client. xAI Grok / OpenAI / Ollama via OpenAI-compatible chat completions with tool calling.
`mock` is an offline heuristic policy (no key) that still decides tool calls from observations."""
import os, json, requests
from dotenv import load_dotenv
load_dotenv()

PROVIDERS = {
 "xai":    ("https://api.x.ai/v1", "XAI_API_KEY", "XAI_MODEL", "grok-3-mini"),
 "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini"),
 "ollama": ("http://localhost:11434/v1", None, "OLLAMA_MODEL", "llama3.1"),
}

class LLM:
    def __init__(self, provider=None):
        self.provider = (provider or os.getenv("LLM_PROVIDER", "mock")).lower()
        if self.provider != "mock":
            self.base, key_env, model_env, default = PROVIDERS[self.provider]
            self.key = os.getenv(key_env) if key_env else "ollama"
            self.model = os.getenv(model_env, default)
            if not self.key: raise RuntimeError(f"{key_env} not set (see .env.example), or use LLM_PROVIDER=mock")
        else: self.model = "offline-heuristic"

    def chat(self, messages, tools):
        """Returns {content, tool_calls:[{id,name,args}]}."""
        if self.provider == "mock":
            from .mock_llm import step
            return step(messages)
        r = requests.post(f"{self.base}/chat/completions", headers={"Authorization": f"Bearer {self.key}"},
            json=dict(model=self.model, messages=messages, tools=tools, tool_choice="auto", temperature=0.1), timeout=120)
        if r.status_code >= 400: raise RuntimeError(f"{self.provider} {r.status_code}: {r.text[:300]}")
        m = r.json()["choices"][0]["message"]
        calls = [dict(id=c["id"], name=c["function"]["name"], args=json.loads(c["function"]["arguments"] or "{}")) for c in m.get("tool_calls") or []]
        return dict(content=m.get("content") or "", tool_calls=calls)
