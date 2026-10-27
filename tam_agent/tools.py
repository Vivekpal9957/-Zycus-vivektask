"""Agent tools. Indexes are built once; the LLM only ever sees small, ranked slices."""
import re, math, difflib, datetime as dt
from collections import Counter, defaultdict
from functools import lru_cache
from . import data, kb as kbmod, schema

TODAY = dt.date(2026, 5, 23)  # day after the newest ticket in the dataset
OPEN = ("Open", "In Progress", "Pending Customer")
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

def norm(n): return re.sub(r"\b(inc|ltd|corp|corporation|llc|group|holdings|co|company)\b", "", re.sub(r"[^a-z0-9 ]", " ", n.lower())).split()
def norm_key(n): return " ".join(re.sub(r"[^a-z0-9 ]", "", n.lower()).split())

@lru_cache(maxsize=1)
def S():
    """Lazy singleton holding all indexes. Tickets are joined to accounts by company name: most ticket account_ids are absent from accounts.json."""
    st = type("S", (), {})()
    st.accounts = {a["account_id"]: a for a in data.load_accounts()}
    st.by_company = {norm_key(a["company"]): a["account_id"] for a in st.accounts.values()}
    st.tickets = {t["ticket_id"]: t for t in data.load_tickets()}
    st.tlist = list(st.tickets.values())
    st.tbm = BM25([t["subject"]+" "+t["body"] for t in st.tlist])
    st.by_acc = defaultdict(list)
    for i, t in enumerate(st.tlist):
        aid = st.by_company.get(norm_key(t["company"]))
        if aid: st.by_acc[aid].append(i)
    st.kb = {a["id"]: a for a in kbmod.load_kb()}; st.klist = list(st.kb.values())
    st.kbm = BM25([a["title"]+" "+a["title"]+" "+a["category"]+" "+a["body"] for a in st.klist])
    return st

# ---------------- tools ----------------
def resolve_account(company="", account_id="", **_):
    """Match on account_id first (often unknown to accounts.json), then on company name. Close name matches are flagged AMBIGUOUS."""
    st = S(); res = []
    a = st.accounts.get(account_id) if account_id else None
    if a: res.append((.99, a, [f"account_id {account_id} exists"]))
    if company:
        for a in st.accounts.values():
            if res and a is res[0][1]: continue
            r = difflib.SequenceMatcher(None, " ".join(norm(company)), " ".join(norm(a["company"]))).ratio()
            if norm_key(company) == norm_key(a["company"]): r = 1.0
            if r > .6:
                ev = [f"company name similarity {r:.2f}"] + ([f"ticket account_id {account_id} not in accounts"] if account_id and account_id not in st.accounts else [])
                res.append((.95 if r == 1 else r * .9, a, ev))
    res.sort(key=lambda x: -x[0])
    cands = [dict(account_id=a["account_id"], company=a["company"], tier=a["plan_tier"], tam=a["tam"], confidence=round(sc, 2), evidence=ev) for sc, a, ev in res[:3]]
    note = ""
    if not cands: note = "No match on id or company name."
    elif len(cands) > 1 and cands[0]["confidence"]-cands[1]["confidence"] < .15: note = "AMBIGUOUS: top candidates are close; do not guess."
    return dict(candidates=cands, note=note)

def get_account_context(account_id, **_):
    st = S(); a = st.accounts.get(account_id)
    if not a: return dict(error=f"unknown account {account_id}")
    idx = st.by_acc[account_id]; cutoff = (TODAY - dt.timedelta(days=90)).isoformat()
    return dict(account={k: a[k] for k in ("account_id", "company", "plan_tier", "tam", "arr_usd", "health_status", "usage_trend", "nps_score", "products", "customer_since", "last_qbr_date")},
                days_to_renewal=(dt.date.fromisoformat(a["renewal_date"])-TODAY).days, renewal_date=a["renewal_date"],
                seats=dict(licensed=a["seats_licensed"], active=a["seats_active"], utilization_pct=round(100*a["seats_active"]/max(1, a["seats_licensed"]))),
                p1_tickets_last_30d=a["p1_tickets_last_30d"], open_tickets_reported=a["open_tickets"], escalation_notes=a["escalation_notes"],
                tickets_last_90d=sum(1 for i in idx if st.tlist[i]["created_at"][:10] >= cutoff), open_tickets_in_data=sum(1 for i in idx if st.tlist[i]["status"] in OPEN))

def search_tickets(account_id="", query="", exclude_ticket_id="", **_):
    st = S(); idx = st.by_acc.get(account_id, []) if account_id else None
    out = []
    for sc, i in st.tbm.top(query, 12, idx):
        t = st.tlist[i]
        if t["ticket_id"] == exclude_ticket_id: continue
        out.append(dict(ticket_id=t["ticket_id"], created=t["created_at"][:10], status=t["status"], product=t["product"], subject=t["subject"], score=round(sc, 1)))
        if len(out) == 5: break
    return dict(results=out)

def get_ticket(ticket_id, **_):
    t = S().tickets.get(ticket_id); return t or dict(error="not found")

def search_kb(query, **_):
    """BM25 over KB sections. Sections mentioning deprecated/EOL versions are flagged so the agent checks the customer's version."""
    st = S(); r = [(sc, st.klist[i]) for sc, i in st.kbm.top(query, 5)]
    return dict(results=[dict(id=a["id"], title=a["title"], category=a["category"], snippet=a["body"][:160].replace("\n", " "), score=round(sc, 1),
        **({"WARNING": "mentions deprecated/EOL versions - check the customer's version"} if a["deprecated"] else {})) for sc, a in r])

def get_kb_article(article_id, **_):
    a = S().kb.get(article_id)
    if not a: return dict(error="not found")
    return dict(id=a["id"], title=a["title"], source=a["source"], body=a["body"][:2500], **({"WARNING": "mentions deprecated/EOL versions"} if a["deprecated"] else {}))

TOOLS = dict(resolve_account=resolve_account, get_account_context=get_account_context, search_tickets=search_tickets,
             get_ticket=get_ticket, search_kb=search_kb, get_kb_article=get_kb_article)

def _fn(name, desc, props, req):
    return dict(type="function", function=dict(name=name, description=desc, parameters=dict(type="object", properties={k: dict(type="string", description=v) for k, v in props.items()}, required=req)))

SPECS = [
 _fn("resolve_account", "Resolve the customer account from the ticket's company name and account_id. The ticket's account_id is often NOT in accounts.json, so always check by company name. Returns ranked candidates with confidence; may flag AMBIGUOUS.", dict(company="Company name as written", account_id="account_id from the ticket (may be unknown)"), []),
 _fn("get_account_context", "Get plan tier, TAM, renewal date, days to renewal, health status, usage trend, seat utilization, P1s in last 30d, escalation notes (churn signals).", dict(account_id="resolved account id from resolve_account, e.g. ACC-3336"), ["account_id"]),
 _fn("search_tickets", "Search past/open tickets (BM25) restricted to the resolved account. Use to find duplicates and history.", dict(account_id="resolved account id", query="keywords", exclude_ticket_id="the current ticket id"), ["query"]),
 _fn("get_ticket", "Fetch one ticket in full by id.", dict(ticket_id="e.g. TKT-10228"), ["ticket_id"]),
 _fn("search_kb", "Search the knowledge base (product docs, troubleshooting, billing, onboarding). Results are sections with ids like 'cloudsync#2'; deprecated-version sections are flagged.", dict(query="keywords"), ["query"]),
 _fn("get_kb_article", "Read one full KB section by id.", dict(article_id="e.g. billing-and-plans#4"), ["article_id"]),
 dict(type="function", function=dict(name="submit_triage", description="FINAL step. Submit the triage decision. Validated against the schema; errors are returned so you can fix them.",
   parameters=dict(type="object", properties=dict(
     account_id=dict(type=["string", "null"]), account_confidence=dict(type="number"),
     category=dict(type="string", enum=schema.CATEGORIES), priority=dict(type="string", enum=schema.PRIORITIES), routing=dict(type="string", enum=schema.ROUTES),
     escalate=dict(type="boolean"), escalation_reason=dict(type=["string", "null"]), notify_tam=dict(type="boolean"),
     is_duplicate=dict(type="boolean"), duplicate_of=dict(type=["string", "null"]),
     needs_clarification=dict(type="boolean"), clarification_questions=dict(type="array", items=dict(type="string")),
     kb_articles=dict(type="array", items=dict(type="string")), customer_reply=dict(type="string"), internal_note=dict(type="string")),
     required=["account_id","account_confidence","category","priority","routing","escalate","escalation_reason","notify_tam","is_duplicate","duplicate_of","needs_clarification","clarification_questions","kb_articles","customer_reply","internal_note"])))]
