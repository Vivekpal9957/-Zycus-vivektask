"""Dataset integrity: row counts, review ids, and how many ticket account_ids resolve (the starter data has many that do not)."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tam_agent import data, kb
from tam_agent.tools import norm_key
acc = data.load_accounts(); tix = data.load_tickets(); arts = kb.load_kb()
ids = {a["account_id"] for a in acc}; names = {norm_key(a["company"]) for a in acc}
errs = [f"ticket {t['ticket_id']}: company {t['company']!r} not in accounts" for t in tix if norm_key(t["company"]) not in names]
tid = {t["ticket_id"] for t in tix}; errs += [f"review id {i} missing" for i in data.load_review_ids() if i not in tid]
print(f"{len(acc)} accounts, {len(tix)} tickets ({sum(t['account_id'] not in ids for t in tix)} with account_id not in accounts.json, matched by company name instead), {len(arts)} KB sections")
print("OK" if not errs else "\n".join(errs[:20])); sys.exit(bool(errs))
