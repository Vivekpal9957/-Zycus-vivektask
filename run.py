"""Run the agent: python run.py --set review [--provider mock|xai] [--ticket TCK-9001]"""
import argparse, json, time, pathlib
from tam_agent import data, agent, schema
from tam_agent.llm import LLM
ap = argparse.ArgumentParser(); ap.add_argument("--set", default="review"); ap.add_argument("--ticket"); ap.add_argument("--provider"); ap.add_argument("--n", type=int, default=20)
a = ap.parse_args()
T = {t["ticket_id"]: t for t in data.load_tickets()}
ids = [a.ticket] if a.ticket else data.load_review_ids() if a.set == "review" else list(T)[:a.n]
out = pathlib.Path("outputs"); out.mkdir(exist_ok=True); llm = LLM(a.provider)
log = open(out / "run_log.jsonl", "w")
for tid in ids:
    t0 = time.time(); events = []
    r = agent.triage(T[tid], on_event=events.append, llm=llm)
    (out / f"{tid}.json").write_text(json.dumps(r, indent=2))
    log.write(json.dumps(dict(ticket_id=tid, provider=llm.provider, model=llm.model, seconds=round(time.time() - t0, 2), tool_calls=len(events) - 1,
        tools=[e["tool"] for e in events if e["type"] == "step"], valid=not schema.validate(r))) + "\n")
    print(f"{tid} {r['priority']} {r['category']:<15} -> {r['routing']:<18} tools={[e['tool'] for e in events if e['type']=='step']}")
