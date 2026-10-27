# SOLUTION

> Note: the starter I received had only data (500 tickets, 50 accounts, 9 KB docs), with no `schema.py`, review set, `check_outputs.py` or loaders. So I wrote `schema.py` (our own output contract), `check_outputs.py`, and picked the 10 review tickets (`data/review_set.txt`) myself.

## Design
A genuine tool-calling loop (`tam_agent/agent.py`): the LLM sees one ticket, chooses a tool, reads the result, and decides the next step or stops by calling `submit_triage` (max 12 steps). Nothing is fixed: depth varies per ticket (4–12 tool calls in the real run, avg 7).
Tools (`tools.py`): `resolve_account` (ticket account_id is mostly NOT in accounts.json, so it matches by company name too; id/name conflicts or close names are flagged AMBIGUOUS), `get_account_context` (tier, TAM, renewal, health, seat use, escalation notes), `search_tickets` (BM25, account-scoped → duplicates), `get_ticket`, `search_kb` (BM25 over KB sections; deprecated/EOL sections flagged), `get_kb_article`.
`submit_triage` is validated against `schema.py`; errors go back to the model to fix. A fallback guarantees a valid file. Every tool call + observation + reasoning sentence goes in `reasoning_trace`. Ticket text is treated as untrusted (injection test in tests/). Providers: Groq, xAI, OpenAI, Ollama via one OpenAI-compatible client.
UI: `python -m ui.server` streams each step live (SSE) with account health, KB citations and the decision.

## Evaluation (before production)
- Gold-label ~300 tickets with TAMs; track accuracy/F1 for category, priority (off-by-one weighted), routing; recall on escalate/notify-TAM (misses cost more than false alarms).
- Account resolution accuracy on blank/lookalike names, with abstention rate.
- KB retrieval: recall@5 and MRR vs. TAM-chosen articles; rate of citing outdated articles (target 0).
- Duplicate precision/recall; adversarial suite (injection, vague, conflicting signals).
- Trajectory metrics: tool calls per ticket, wasted/repeated calls, step-cap hits, schema-fix retries.
- Reply quality via rubric LLM-judge + human spot checks; shadow-mode with TAM override rate before auto-routing.

## Scale (10x: 30k tickets, 4k articles)
Nothing large enters a prompt, so token cost per ticket is flat (~5–8 calls). In-memory BM25 is fine at this size but retrieval quality drops with 4k near-duplicate articles: add embeddings + hybrid rank fusion, a reranker, metadata filters (product/version/edition), and a vector/Postgres store with incremental indexing. Tickets: per-account index keeps history search cheap. Latency is dominated by sequential LLM calls (~2–4 s each): cache account context, run independent lookups in parallel, use a small model for easy tickets. Stale-article detection should be an offline job.

## Observed results (real run, Groq `openai/gpt-oss-20b`)
- 10/10 schema-valid, but only **7 of 10 outputs are from the real LLM** (TKT-10035, 10036, 10042, 10078, 10112, 10184, 10002). TKT-10005, 10017, 10048 are from the offline mock: Groq's free daily token cap hit mid-session and I stopped the run. Re-run `python run.py --set review` to regenerate them.
- Tool calls on the real tickets ranged 4–12, so depth varies. Duplicate found: TKT-10035 -> TKT-10228 (same account, same problem). Ticket account_id/company mismatches (TKT-10042, 10078) were noticed and the agent asked for clarification instead of guessing.
- What failed / fixed: Groq retired llama-3.3 (switched model); 429 rate limits (retry/backoff in llm.py; each ticket takes 2–4 min on the free tier); `tool_calls: null` caused a 400 (fixed); the 120b model's daily cap forced the move to 20b.
- Not verified: no gold labels; the starter KB has no "outdated article" or policy docs, so those checks from the brief could not be tested. Priorities e.g. TKT-10184 (an upgrade request) coming out as P1 look too high and are not fixed.

## Limitations
- 3 of 10 committed outputs are mock; routing is mostly L1_support (the 20b model under-uses escalation). Tests use the offline mock, which says little about LLM quality.
- Lexical retrieval only; no embeddings. Account matching is heuristic. Priority/escalation rules live in prompt + KB, not a tested rules engine. No auth on the UI; no retries/rate-limit handling for Grok free-trial limits.

## How to run
```bash
pip install -r requirements.txt
cp .env.example .env              # set XAI_API_KEY (Grok) or LLM_PROVIDER=mock
python run.py --set review [--provider xai]
python scripts/check_outputs.py   # 10/10 valid
python -m ui.server               # http://localhost:8000
```
