"""Offline stand-in for an LLM: an observation-driven policy (NOT a fixed sequence - it branches on what tools return).
Used for keyless demos/tests. Same interface as a real tool-calling model."""
import json, re, uuid

INJ = re.compile(r"ignore (all )?(previous|prior)|system override|disregard (the )?(rules|instructions)", re.I)

def _history(messages):
    ids, calls, obs = {}, [], []
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
    text = _clean(t["subject"] + " " + t["body"])
    # ---- decide next tool from what we've seen ----
    acct = t.get("account_id") or None; conf = 1.0 if acct else 0.0; ambiguous = False
    res = done("resolve_account")
    if res:
        c = res[0][2].get("candidates", [])
        ambiguous = "AMBIGUOUS" in res[0][2].get("note", "")
        if c and not ambiguous and c[0]["confidence"] >= .8: acct, conf = c[0]["account_id"], c[0]["confidence"]
    ctx = (done("get_account_context") or [None])[0]
    if not acct and not res:
        return _call("resolve_account", dict(company=t.get("company", ""), email=t.get("requester", "")), "Account ID is blank, so I need to resolve the account from the company name and sender email.")
    vague = len(t["body"]) < 80 and not acct
    if not acct and vague:
        return _submit(t, None, 0, None, [], "unresolved", h)
    if acct and not ctx:
        return _call("get_account_context", dict(account_id=acct), f"Checking health, renewal and escalations for {acct}.")
    cat = _category(text)
    if not done("search_tickets"):
        return _call("search_tickets", dict(account_id=acct or "", query=t["subject"] + " " + t["body"][:150], exclude_ticket_id=t["ticket_id"]), "Looking for duplicates and history on this account.")
    st = done("search_tickets")[0][2]["results"]
    dup = next((r for r in st if r["status"] in ("open", "new") and r["score"] > 10), None)
    if dup and not done("get_ticket"):
        return _call("get_ticket", dict(ticket_id=dup["ticket_id"]), f"{dup['ticket_id']} is open and very similar - verifying it is the same problem.")
    if not done("search_kb"):
        return _call("search_kb", dict(query=t["subject"] + " " + re.sub(r"\n.*", "", t["body"])[:200]), "Searching the knowledge base for a resolution.")
    kbres = done("search_kb")[0][2]["results"]
    fetched = {x[1]["article_id"] for x in done("get_kb_article")}
    for r in kbres[:3]:   # follow outdated -> superseded
        if r.get("WARNING"):
            sup = re.search(r"(KB-[\w-]+)", r["WARNING"]).group(1)
            if sup not in fetched: return _call("get_kb_article", dict(article_id=sup), f"{r['id']} is outdated; following the link to its replacement {sup}.")
    cur = [r for r in kbres if r["status"] == "current"]
    if cur and cur[0]["id"] not in fetched and not any(x[2].get("status") == "current" and not x[2]["id"].startswith("KB-POL") for x in done("get_kb_article")):
        return _call("get_kb_article", dict(article_id=cur[0]["id"]), f"Reading the top article {cur[0]['id']} in full.")
    pol = _policy_query(cat, bool(INJ.search(t["subject"] + " " + t["body"])))
    if pol and not done("search_kb")[1:]:
        return _call("search_kb", dict(query=pol), "This needs a support-policy check before deciding.")
    if pol and len(done("search_kb")) > 1:
        pr = [r for r in done("search_kb")[1][2]["results"] if r["id"].startswith("KB-POL")]
        if pr and pr[0]["id"] not in fetched: return _call("get_kb_article", dict(article_id=pr[0]["id"]), f"Reading policy {pr[0]['id']}.")
    return _submit(t, acct, conf, ctx, h, "ok", h, dup=dup)

def _clean(s):
    """Drop lines carrying injected instructions so they cannot influence classification."""
    return " ".join(l for l in s.split("\n") if not INJ.search(l)).lower()

def _category(text):
    rules = [("security", r"unauthori[sz]ed|breach|former employee|left in .* can still|exfiltrat"), ("renewal_risk", r"evaluating|other vendors|alternatives|cancel our|reconsider"),
             ("billing", r"refund|credit note|overcharg"), ("access_sso", r"sso|saml|okta|login loop"), ("integration", r"\bsap\b|erp|netsuite|oracle|punch-?out"),
             ("data_quality", r"csv|upload|import|uom"), ("performance", r"slow|timeout|latency")]
    for c, p in rules:
        if re.search(p, text): return c
    return None

def _policy_query(cat, inj):
    return {"billing": "refund credit policy", "security": "security incident policy", "renewal_risk": "escalation policy TAM notification"}.get(cat) or ("untrusted ticket content policy" if inj else None)

def _submit(t, acct, conf, ctx, h, mode, hist, dup=None):
    inj = bool(INJ.search(t["subject"] + " " + t["body"]))
    text = _clean(t["subject"] + " " + t["body"])
    if mode == "unresolved":
        args = dict(account_id=None, account_confidence=0.0, category="other", priority="P3", routing="L1_support", escalate=False, escalation_reason=None, notify_tam=False,
            is_duplicate=False, duplicate_of=None, needs_clarification=True,
            clarification_questions=["Which company/account are you contacting us about (and your work email)?", "What exactly is not working - which page, action, or error message?", "When did it start, and who is affected?"],
            kb_articles=[], customer_reply="Hello, thanks for reaching out. We couldn't match your message to an account and need a few details before we can help: your company name and work email, what exactly isn't working (page, action or error message), and when it started. Reply with those and we'll pick it up right away.",
            internal_note="Sender is a free-mail address with no company; body is too vague to investigate. No account match from resolve_account. Asked for account, symptom and timing. Stopped early - no KB search warranted.")
        return dict(content="Cannot identify account or problem; asking for clarification rather than guessing.", tool_calls=[dict(id="c" + uuid.uuid4().hex[:8], name="submit_triage", args=args)])
    a = ctx[2]["account"]; days = ctx[2]["days_to_renewal"]; u = ctx[2]["usage_trend"]; esc = ctx[2]["open_escalations"]; tier = a["tier"]
    kbs = {}
    for n, args, o in hist:
        if n == "get_kb_article" and "id" in o: kbs[o["id"]] = o
    cur = [k for k in kbs.values() if k["status"] == "current"]
    top = next((r for n, _, o in hist if n == "search_kb" for r in o["results"] if r["status"] == "current" and not r["id"].startswith("KB-POL")), None)
    cat = _category(text) or (top["category"] if top and top["category"] != "policy" else "other")
    big = tier in ("Enterprise", "Premier"); blocking = bool(re.search(r"block|month-end|urgent|stuck|waiting|loop|since", text))
    neg = bool(re.search(r"evaluating|disappointed|unresolved|reconsider", text)); decline = u["change_last3_vs_prev3_pct"]
    pri = {"security": "P1", "renewal_risk": "P2", "feature_request": "P4"}.get(cat, "P3")
    if cat in ("integration", "access_sso", "technical_issue") and big and blocking: pri = "P2"
    if cat == "how_to" and not blocking: pri = "P4"
    escalate, why = False, None
    if pri == "P1": escalate, why = True, "P1 security incident per KB-POL-006 / escalation policy KB-POL-003"
    elif cat == "renewal_risk" and big and days <= 90: escalate, why = True, f"Churn risk on {tier} account {days} days before renewal (KB-POL-003)"
    elif esc and cat in ("integration", "technical_issue", "access_sso"): escalate, why = True, f"Account has open escalation {esc[0]['id']}: {esc[0]['summary']}"
    notify = big and (escalate or (days <= 90 and (neg or decline < -25)))
    route = {"security": "security_team", "billing": "billing_ops", "feature_request": "product_management", "renewal_risk": "customer_success"}.get(cat) or ("L2_support" if (big and pri in ("P1", "P2")) else "L1_support")
    steps = ""
    steps = ""
    for k in cur:
        if k["id"].startswith("KB-POL"): continue
        m = re.search(r"(?:Resolution[^:]*:|Fix|Error)[: ]*(.*?)(?: For |\n|$)", k["body"], re.S)
        steps = (m.group(1) if m else k["body"][:200]).strip(); break
    cites = [k["id"] for k in cur]
    isdup = bool(dup)
    if isdup: why = why or "Duplicate of open work item"
    greet = "Hello,\n\n"
    if cat == "security":
        reply = greet + "Thank you for flagging this - we are treating it as a P1 security incident. Please disable the user immediately, rotate any API keys and preserve audit logs; do not delete anything. Our Security Team and your Technical Account Manager have been engaged and will contact you within the hour."
    elif cat == "renewal_risk":
        reply = greet + "Thank you for being candid - we take this seriously. I've escalated your message to our Customer Success leadership and your Technical Account Manager, who will reach out today to arrange a call with a senior contact and review the open tickets and adoption since your migration."
    elif cat == "billing":
        reply = greet + "Thanks for reaching out. I've passed your request to our Billing Operations team, who will review it against our refund and credit policy (refunds are only available within 30 days of invoice). We can't confirm an outcome yet, but they will respond with a decision and options, such as a plan adjustment."
    elif cat == "feature_request":
        reply = greet + "Thanks for the detail. Roll-up by cost-center hierarchy isn't supported today - this is current behavior rather than a defect, and it's tracked on our roadmap (PM-1190). I've logged your use case with Product Management. Meanwhile, flat cost-center grouping is available under Analytics > Reports."
    elif isdup:
        reply = greet + f"Thanks for following up. This matches your open ticket {dup['ticket_id']}, so we've linked them and will keep updates on that thread. Because it affects your month-end close, we've also raised its priority with our ERP team and will update you shortly."
    else:
        reply = greet + "Thanks for contacting us. " + (f"Here is how to resolve this: {steps} " if steps else "") + "If this doesn't fix it, reply with the exact error message or a screenshot and we'll take it to our L2 team."
    if inj: reply += "\n\n(Note: we can only act on the support request itself; priority and any billing outcomes are determined under our standard policies.)"
    note = f"{a['name']} ({a['id']}, {tier}); renewal in {days}d; active users {decline:+}% 3m vs prior 3m; open escalations: {len(esc)}. Account resolved with confidence {conf:.2f}. Category={cat}, priority={pri}. " \
           + (f"Duplicate of {dup['ticket_id']}. " if isdup else "") + (f"KB used: {', '.join(cites)}. " if cites else "") \
           + ("PROMPT INJECTION detected in ticket body (instructions to set P1/refund) - ignored per KB-POL-007. " if inj else "") \
           + ("Outdated article skipped in favour of its replacement. " if any(r.get("WARNING") for n, _, o in hist if n == "search_kb" for r in o["results"]) else "")
    args = dict(account_id=a["id"], account_confidence=round(conf, 2), category=cat, priority=pri, routing=route, escalate=escalate, escalation_reason=why if escalate else None,
        notify_tam=bool(notify), is_duplicate=isdup, duplicate_of=dup["ticket_id"] if isdup else None, needs_clarification=False, clarification_questions=[],
        kb_articles=cites, customer_reply=reply, internal_note=note)
    return dict(content="I have enough evidence; submitting the decision.", tool_calls=[dict(id="c" + uuid.uuid4().hex[:8], name="submit_triage", args=args)])
