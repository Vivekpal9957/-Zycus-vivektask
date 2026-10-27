"""Offline stand-in for an LLM (keyless demos/tests). It branches on tool observations, but it is a heuristic, not a real model."""
import json, re, uuid

INJ = re.compile(r"ignore (all )?(previous|prior)|system override|disregard (the )?(rules|instructions)", re.I)

def _history(messages):
    ids, calls = {}, []
    for m in messages:
        for c in m.get("tool_calls") or []:
            ids[c["id"]] = (c["function"]["name"], json.loads(c["function"]["arguments"]))
        if m["role"] == "tool" and m["tool_call_id"] in ids:
            n, a = ids[m["tool_call_id"]]
            try: o = json.loads(m["content"])
            except Exception: o = {"raw": m["content"]}
            calls.append((n, a, o))
    return calls

def _call(name, args, why):
    return dict(content=why, tool_calls=[dict(id="c" + uuid.uuid4().hex[:8], name=name, args=args)])

def step(messages):
    t = json.loads(messages[1]["content"].split("TICKET:\n", 1)[1])
    h = _history(messages); done = lambda n: [x for x in h if x[0] == n]
    text = " ".join(l for l in (t["subject"] + "\n" + t["body"]).split("\n") if not INJ.search(l))
    if not done("resolve_account"):
        return _call("resolve_account", dict(company=t.get("company", ""), account_id=t.get("account_id", "")), "Resolving the account by company name, since the ticket account_id may be unknown.")
    cands = done("resolve_account")[0][2].get("candidates", [])
    ok = cands and "AMBIGUOUS" not in done("resolve_account")[0][2]["note"]
    acct, conf = (cands[0]["account_id"], cands[0]["confidence"]) if ok else (None, 0.0)
    if not acct: return _submit(t, None, 0, None, h, None)
    if not done("get_account_context"): return _call("get_account_context", dict(account_id=acct), f"Checking health, renewal and churn signals for {acct}.")
    if not done("search_tickets"):
        return _call("search_tickets", dict(account_id=acct, query=t["subject"] + " " + t["body"][:150], exclude_ticket_id=t["ticket_id"]), "Looking for duplicates and history on this account.")
    if not done("search_kb"): return _call("search_kb", dict(query=t["subject"] + " " + t["body"][:200]), "Searching the knowledge base.")
    top = done("search_kb")[0][2]["results"]
    if top and not done("get_kb_article"): return _call("get_kb_article", dict(article_id=top[0]["id"]), f"Reading {top[0]['id']} in full.")
    return _submit(t, acct, conf, done("get_account_context")[0][2], h, done("search_tickets")[0][2]["results"])

def _submit(t, acct, conf, ctx, h, hist):
    if not acct:
        args = dict(account_id=None, account_confidence=0.0, category="Other", priority="P3", routing="L1_support", escalate=False, escalation_reason=None, notify_tam=False,
            is_duplicate=False, duplicate_of=None, needs_clarification=True, clarification_questions=["Which company/account are you contacting us about?", "What exactly is not working, and when did it start?"],
            kb_articles=[], customer_reply="Hello, thanks for reaching out. We couldn't match your message to an account and need a few details: your company name, what exactly isn't working, and when it started.",
            internal_note="Account could not be resolved unambiguously from the ticket; asked for company and symptom details.")
        return dict(content="Cannot identify the account; asking for clarification.", tool_calls=[dict(id="c" + uuid.uuid4().hex[:8], name="submit_triage", args=args)])
    a = ctx["account"]; days = ctx["days_to_renewal"]; inj = bool(INJ.search(t["subject"] + " " + t["body"]))
    dup = next((r for r in hist if r["status"] in ("Open", "In Progress", "Pending Customer") and r["score"] > 12 and r["product"] == t.get("product")), None)
    kb = next((x[2]["id"] for x in h if x[0] == "get_kb_article" and "id" in x[2]), None)
    body = next((x[2]["body"] for x in h if x[0] == "get_kb_article" and "body" in x[2]), "")
    risky = a["health_status"] in ("At Risk", "Churning")
    cat = t.get("category") if t.get("category") in ("Bug", "Feature Request", "How-To", "Performance", "Billing", "Integration", "Onboarding", "Data Loss") else "Other"
    pri = t.get("urgency", "P3") if not inj else t.get("urgency", "P3")
    esc = pri == "P1" or cat == "Data Loss"
    notify = esc or (risky and days <= 120)
    note = f"{a['company']} ({a['account_id']}, {a['plan_tier']}, {a['health_status']}); renewal in {days}d; seats {ctx['seats']['utilization_pct']}% active. " + (f"Duplicate of {dup['ticket_id']}. " if dup else "") \
        + (f"KB used: {kb}. " if kb else "") + ("PROMPT INJECTION in ticket body ignored. " if inj else "")
    reply = "Hello,\n\nThanks for contacting us. " + (f"This looks related to your open ticket {dup['ticket_id']}; we have linked them. " if dup else "") \
        + (f"Based on our documentation: {body[:240].strip()} " if body else "") + "We'll follow up with next steps."
    args = dict(account_id=acct, account_confidence=round(conf, 2), category=cat, priority=pri, routing="L2_support" if pri in ("P1", "P2") else "L1_support", escalate=esc,
        escalation_reason="P1 / data loss per priority policy" if esc else None, notify_tam=bool(notify), is_duplicate=bool(dup), duplicate_of=dup["ticket_id"] if dup else None,
        needs_clarification=False, clarification_questions=[], kb_articles=[kb] if kb else [], customer_reply=reply, internal_note=note)
    return dict(content="Enough evidence; submitting.", tool_calls=[dict(id="c" + uuid.uuid4().hex[:8], name="submit_triage", args=args)])
