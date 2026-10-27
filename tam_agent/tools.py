"""Agent tools. Indexes are built once; the LLM only ever sees small, ranked slices."""
import re, math, difflib, datetime as dt
from collections import Counter, defaultdict
from functools import lru_cache
from . import data, kb as kbmod

TODAY = dt.date(2026, 10, 27)
STOP = set("the a an and or of to in on for is are was were be it we our you your with that this not no can how what why from at by as please any have has had since".split())
tok = lambda s: [w for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1]

class BM25:
    def __init__(s, docs, k1=1.4, b=.75):
        s.docs = [Counter(tok(d)) for d in docs]; s.len = [sum(c.values()) for c in s.docs]
        s.avg = sum(s.len)/max(1,len(docs)); s.k1, s.b = k1, b
        df = Counter(w for c in s.docs for w in c); n = len(docs)
        s.idf = {w: math.log(1+(n-f+.5)/(f+.5)) for w, f in df.items()}
    def score(s, q, i):
        c, L, sc = s.docs[i], s.len[i], 0.
        for w in set(tok(q)):
            if w in c: sc += s.idf[w]*c[w]*(s.k1+1)/(c[w]+s.k1*(1-s.b+s.b*L/s.avg))
        return sc
    def top(s, q, k=5, idx=None):
        r = sorted(((s.score(q, i), i) for i in (idx if idx is not None else range(len(s.docs)))), reverse=True)
        return [(sc, i) for sc, i in r[:k] if sc > 0]

@lru_cache(maxsize=1)
def S():
    """Lazy singleton holding all indexes."""
    st = type("S", (), {})()
    st.accounts = {a["id"]: a for a in data.load_accounts()}
    st.usage = defaultdict(list)
    for u in data.load_usage(): st.usage[u["account_id"]].append(u)
    st.esc = defaultdict(list)
    for e in data.load_escalations(): st.esc[e["account_id"]].append(e)
    st.tickets = {t["ticket_id"]: t for t in data.load_tickets()}
    st.tlist = list(st.tickets.values())
    st.tbm = BM25([t["subject"]+" "+t["body"] for t in st.tlist])
    st.by_acc = defaultdict(list)
    for i, t in enumerate(st.tlist):
        if t["account_id"]: st.by_acc[t["account_id"]].append(i)
    st.kb = {a["id"]: a for a in kbmod.load_kb()}; st.klist = list(st.kb.values())
    st.kbm = BM25([a["title"]+" "+a["title"]+" "+a["category"]+" "+a["body"] for a in st.klist])
    return st

def norm(n): return re.sub(r"\b(inc|ltd|corp|corporation|llc|group|holdings|co)\b", "", re.sub(r"[^a-z0-9 ]", " ", n.lower())).split()

# ---------------- tools ----------------
def resolve_account(company="", email="", **_):
    st = S(); dom = email.split("@")[-1].lower() if "@" in email else ""
    free = dom in ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com")
    res = []
    for a in st.accounts.values():
        ev, sc = [], 0.
        if dom and not free and dom == a["domain"]: sc += .7; ev.append(f"email domain matches {a['domain']}")
        if company:
            r = difflib.SequenceMatcher(None, " ".join(norm(company)), " ".join(norm(a["name"]))).ratio()
            if r > .6: sc += .3*r if dom else .9*r; ev.append(f"name similarity {r:.2f}")
        if sc > 0: res.append((sc, a, ev))
    res.sort(key=lambda x: -x[0])
    cands = [dict(account_id=a["id"], name=a["name"], tier=a["tier"], domain=a["domain"], confidence=round(min(sc, .99), 2), evidence=ev) for sc, a, ev in res[:3]]
    note = ""
    if not cands: note = "No match. Free-mail sender and no usable company name." if free or not company else "No match."
    elif len(cands) > 1 and cands[0]["confidence"]-cands[1]["confidence"] < .15: note = "AMBIGUOUS: top candidates are close; do not guess."
    return dict(candidates=cands, note=note)

def get_account_context(account_id, **_):
    st = S(); a = st.accounts.get(account_id)
    if not a: return dict(error=f"unknown account {account_id}")
    u = sorted(st.usage[account_id], key=lambda x: x["month"])
    last3, prev3 = sum(x["active_users"] for x in u[-3:]), sum(x["active_users"] for x in u[-6:-3]) or 1
    first = u[0]["active_users"] or 1
    days = (dt.date.fromisoformat(a["renewal"])-TODAY).days
    esc = [e for e in st.esc[account_id] if e["status"] == "open"]
    return dict(account=a, days_to_renewal=days, usage_trend=dict(active_users_last_month=u[-1]["active_users"], change_last3_vs_prev3_pct=round((last3/prev3-1)*100, 1),
                change_12m_pct=round((u[-1]["active_users"]/first-1)*100, 1), monthly_active_users=[x["active_users"] for x in u]),
                open_escalations=esc, open_tickets=sum(1 for i in st.by_acc[account_id] if st.tlist[i]["status"] in ("open", "new")))

def search_tickets(account_id="", query="", exclude_ticket_id="", **_):
    st = S(); idx = st.by_acc.get(account_id, []) if account_id else None
    out = []
    for sc, i in st.tbm.top(query, 12, idx):
        t = st.tlist[i]
        if t["ticket_id"] == exclude_ticket_id: continue
        out.append(dict(ticket_id=t["ticket_id"], created=t["created"], status=t["status"], subject=t["subject"], score=round(sc, 1)))
        if len(out) == 5: break
    return dict(results=out)

def get_ticket(ticket_id, **_):
    t = S().tickets.get(ticket_id); return t or dict(error="not found")

def search_kb(query, category="", **_):
    st = S(); r = []
    for sc, i in st.kbm.top(query, 10):
        a = st.klist[i]
        if a["status"] == "outdated": sc *= .5
        r.append((sc, a))
    r.sort(key=lambda x: -x[0])
    return dict(results=[dict(id=a["id"], title=a["title"], category=a["category"], status=a["status"],
        **({"WARNING": f"OUTDATED - superseded by {a['superseded_by']}; read that article instead"} if a["status"] == "outdated" else {}),
        snippet=a["body"][:160], score=round(sc, 1)) for sc, a in r[:5]])

def get_kb_article(article_id, **_):
    a = S().kb.get(article_id)
    if not a: return dict(error="not found")
    a = dict(a)
    if a["status"] == "outdated": a["WARNING"] = f"OUTDATED - use {a['superseded_by']}"
    return a

TOOLS = dict(resolve_account=resolve_account, get_account_context=get_account_context, search_tickets=search_tickets,
             get_ticket=get_ticket, search_kb=search_kb, get_kb_article=get_kb_article)

def _fn(name, desc, props, req):
    return dict(type="function", function=dict(name=name, description=desc, parameters=dict(type="object", properties={k: dict(type="string", description=v) for k, v in props.items()}, required=req)))

SPECS = [
 _fn("resolve_account", "Fuzzy-resolve the customer account from company name and requester email. Use when account_id is blank or suspect. Returns ranked candidates with confidence; may flag AMBIGUOUS.", dict(company="Company name as written", email="Requester email"), []),
 _fn("get_account_context", "Get tier, renewal date, days to renewal, 12-month usage trend, open escalations, open ticket count.", dict(account_id="e.g. ACC-0001"), ["account_id"]),
 _fn("search_tickets", "Search past/open tickets (BM25), restricted to an account if account_id given. Use to find duplicates and history.", dict(account_id="optional account filter", query="keywords", exclude_ticket_id="the current ticket id"), ["query"]),
 _fn("get_ticket", "Fetch one ticket in full by id.", dict(ticket_id="e.g. TCK-8801"), ["ticket_id"]),
 _fn("search_kb", "Search the knowledge base (incl. support policy). Results flag OUTDATED articles.", dict(query="keywords"), ["query"]),
 _fn("get_kb_article", "Read a full KB article. Use to follow superseded_by/related links or read policies in full.", dict(article_id="e.g. KB-POL-001"), ["article_id"]),
 dict(type="function", function=dict(name="submit_triage", description="FINAL step. Submit the triage decision. Validated against the schema; errors are returned so you can fix them.",
   parameters=dict(type="object", properties=dict(
     account_id=dict(type=["string", "null"]), account_confidence=dict(type="number"),
     category=dict(type="string", enum=["billing","technical_issue","integration","access_sso","feature_request","how_to","security","data_quality","performance","renewal_risk","other"]),
     priority=dict(type="string", enum=["P1","P2","P3","P4"]),
     routing=dict(type="string", enum=["L1_support","L2_support","engineering","billing_ops","security_team","customer_success","product_management"]),
     escalate=dict(type="boolean"), escalation_reason=dict(type=["string", "null"]), notify_tam=dict(type="boolean"),
     is_duplicate=dict(type="boolean"), duplicate_of=dict(type=["string", "null"]),
     needs_clarification=dict(type="boolean"), clarification_questions=dict(type="array", items=dict(type="string")),
     kb_articles=dict(type="array", items=dict(type="string")), customer_reply=dict(type="string"), internal_note=dict(type="string")),
     required=["account_id","account_confidence","category","priority","routing","escalate","escalation_reason","notify_tam","is_duplicate","duplicate_of","needs_clarification","clarification_questions","kb_articles","customer_reply","internal_note"])))]
