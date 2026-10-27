"""Dataset integrity: row counts and foreign keys."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tam_agent import data, kb
acc = {a["id"] for a in data.load_accounts()}; tix = data.load_tickets(); arts = kb.load_kb(); kid = {a["id"] for a in arts}
errs = []
errs += [f"ticket {t['ticket_id']}: bad account {t['account_id']}" for t in tix if t["account_id"] and t["account_id"] not in acc]
errs += [f"usage: bad account {u['account_id']}" for u in data.load_usage() if u["account_id"] not in acc]
errs += [f"escalation {e['id']}: bad account" for e in data.load_escalations() if e["account_id"] not in acc]
errs += [f"kb {a['id']}: bad superseded_by {a['superseded_by']}" for a in arts if a["superseded_by"] and a["superseded_by"] not in kid]
tid = {t["ticket_id"] for t in tix}; errs += [f"review id {i} missing" for i in data.load_review_ids() if i not in tid]
print(f"{len(acc)} accounts, {len(tix)} tickets ({sum(not t['account_id'] for t in tix)} blank account_id), {len(arts)} KB ({sum(a['status']=='outdated' for a in arts)} outdated)")
print("OK" if not errs else "\n".join(errs[:20])); sys.exit(bool(errs))
