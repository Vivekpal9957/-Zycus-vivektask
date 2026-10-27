"""Output format + validator. The starter kit shipped no schema.py, so this is our own contract (categories match the dataset's ticket categories)."""
CATEGORIES = ["Bug","Feature Request","How-To","Performance","Billing","Integration","Onboarding","Data Loss","Other"]
PRIORITIES = ["P1","P2","P3","P4"]
ROUTES = ["L1_support","L2_support","engineering","billing_ops","security_team","customer_success","product_management"]

FIELDS = {
 "ticket_id":str,"account_id":(str,type(None)),"account_confidence":(int,float),"category":str,"priority":str,"routing":str,
 "escalate":bool,"escalation_reason":(str,type(None)),"notify_tam":bool,"is_duplicate":bool,"duplicate_of":(str,type(None)),
 "needs_clarification":bool,"clarification_questions":list,"kb_articles":list,"customer_reply":str,"internal_note":str,"reasoning_trace":list,
}

def validate(o):
    """Return list of error strings (empty = valid)."""
    if not isinstance(o, dict): return ["output must be an object"]
    e = [f"missing field: {k}" for k in FIELDS if k not in o]
    for k,t in FIELDS.items():
        if k in o and not isinstance(o[k], t): e.append(f"{k}: wrong type {type(o[k]).__name__}")
    if e: return e
    if o["category"] not in CATEGORIES: e.append(f"category must be one of {CATEGORIES}")
    if o["priority"] not in PRIORITIES: e.append(f"priority must be one of {PRIORITIES}")
    if o["routing"] not in ROUTES: e.append(f"routing must be one of {ROUTES}")
    if not 0 <= o["account_confidence"] <= 1: e.append("account_confidence must be in [0,1]")
    if o["is_duplicate"] and not o["duplicate_of"]: e.append("duplicate_of required when is_duplicate")
    if o["escalate"] and not o["escalation_reason"]: e.append("escalation_reason required when escalate")
    if o["needs_clarification"] and not o["clarification_questions"]: e.append("clarification_questions required when needs_clarification")
    if not all(isinstance(x,str) for x in o["kb_articles"]): e.append("kb_articles must be list of ids")
    if len(o["customer_reply"].strip())<20: e.append("customer_reply too short")
    if len(o["internal_note"].strip())<20: e.append("internal_note too short")
    if not o["reasoning_trace"]: e.append("reasoning_trace must not be empty")
    return e
