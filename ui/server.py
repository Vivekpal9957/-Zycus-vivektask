"""Zero-dependency UI server: python -m ui.server  ->  http://localhost:8000"""
import json, pathlib, sys, os
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
ROOT = pathlib.Path(__file__).resolve().parent.parent; sys.path.insert(0, str(ROOT))
from tam_agent import data, agent, tools
from tam_agent.llm import LLM

TICKETS = {t["ticket_id"]: t for t in data.load_tickets()}
REVIEW = data.load_review_ids()
OUT = ROOT / "outputs"

def saved(tid):
    p = OUT / f"{tid}.json"; return json.loads(p.read_text()) if p.exists() else None

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, o, code=200):
        b = json.dumps(o).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path
        if p == "/":
            b = (ROOT / "ui" / "index.html").read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        elif p == "/api/meta":
            self._json(dict(default=os.getenv("LLM_PROVIDER", "mock"), model=os.getenv("GROQ_MODEL", ""),
                            counts=dict(tickets=len(TICKETS), accounts=len(tools.S().accounts), kb=len(tools.S().kb))))
        elif p == "/api/tickets":
            s = (q.get("q", [""])[0]).lower(); which = q.get("set", ["review"])[0]
            ids = REVIEW if which == "review" else [t for t in list(TICKETS)[-400:] if t not in REVIEW][::-1]
            self._json([dict(id=i, subject=TICKETS[i]["subject"], account_id=TICKETS[i]["account_id"], company=TICKETS[i]["company"], status=TICKETS[i]["status"], done=bool(saved(i)))
                        for i in ids if s in (i + TICKETS[i]["subject"] + TICKETS[i]["company"]).lower()][:150])
        elif p.startswith("/api/ticket/"):
            i = p.rsplit("/", 1)[1]; self._json(dict(ticket=TICKETS.get(i), saved=saved(i))) if i in TICKETS else self._json({}, 404)
        elif p.startswith("/api/account/"):
            self._json(tools.get_account_context(p.rsplit("/", 1)[1]))
        elif p.startswith("/api/run/"):
            i = p.rsplit("/", 1)[1]
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Cache-Control", "no-cache"); self.end_headers()
            def emit(e):
                e = {k: v for k, v in e.items() if k != "raw"}
                self.wfile.write(f"data: {json.dumps(e)}\n\n".encode()); self.wfile.flush()
            try:
                llm = LLM(q.get("provider", [None])[0]); emit(dict(type="start", provider=llm.provider, model=llm.model))
                agent.triage(TICKETS[i], on_event=emit, llm=llm)
            except Exception as ex: emit(dict(type="error", message=str(ex)))
        else: self._json({}, 404)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000)); print(f"TAM Triage UI on http://localhost:{port}"); ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
