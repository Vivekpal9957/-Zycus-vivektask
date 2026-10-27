import os, json, pathlib
os.environ["LLM_PROVIDER"] = "mock"
import pytest
from tam_agent import tools as T, agent, schema, data
from tam_agent.llm import LLM

TICKETS = {t["ticket_id"]: t for t in data.load_tickets()}
REVIEW = data.load_review_ids()

def test_ambiguous_name_not_guessed():
    r = T.resolve_account(company="Acme", email="someone@gmail.com")
    assert "AMBIGUOUS" in r["note"] and len(r["candidates"]) >= 2

def test_domain_match_is_confident():
    r = T.resolve_account(company="", email="a@acme.com")
    assert r["candidates"][0]["account_id"] == "ACC-0002"

def test_freemail_no_name_has_no_candidates():
    assert T.resolve_account(company="", email="x@gmail.com")["candidates"] == []

def test_outdated_article_flagged():
    res = T.search_kb(query="SAML certificate rotation Okta")["results"]
    assert any(r["status"] == "outdated" for r in res)
    assert [r for r in res if r["status"] == "current"][0]["id"] == "KB-S01"

def test_duplicate_search_finds_open_ticket():
    ids = [r["ticket_id"] for r in T.search_tickets(account_id="ACC-0005", query="SAP PO export error 4021")["results"]]
    assert "TCK-8801" in ids

def test_mock_agent_outputs_valid():
    llm = LLM("mock")
    for tid in REVIEW:
        assert not schema.validate(agent.triage(TICKETS[tid], llm=llm)), tid

def test_committed_outputs_valid():
    for f in pathlib.Path("outputs").glob("TCK-*.json"):
        assert not schema.validate(json.loads(f.read_text())), f.name

def test_injection_does_not_change_priority():
    r = agent.triage(TICKETS["TCK-9009"], llm=LLM("mock"))
    assert r["priority"] != "P1" and not r["escalate"]
