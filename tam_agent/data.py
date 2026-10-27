"""Loaders only. No joins, no search."""
import json, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
D = ROOT / "data"
def _j(n): return json.loads((D/n).read_text(encoding="utf-8"))
def load_accounts(): return _j("accounts.json")
def load_tickets(): return _j("tickets.json")
def load_review_ids(): return [l.strip() for l in (D/"review_set.txt").read_text().splitlines() if l.strip()]
