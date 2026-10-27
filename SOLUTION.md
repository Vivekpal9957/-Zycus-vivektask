# SOLUTION

> Note: `data/`, `schema.py` and loaders are a reconstruction of the starter kit (not yet swapped for the real files). Committed `outputs/` come from a real LLM run: Groq `openai/gpt-oss-120b`.

## Design
A genuine tool-calling loop (`tam_agent/agent.py`): the LLM sees one ticket, chooses a tool, reads the result, and decides the next step or stops by calling `submit_triage` (max 12 steps). Nothing is fixed: a vague free-mail ticket takes 2 calls (resolve → clarify); a security ticket takes 7 (context, history, KB, policy search, policy read).
Tools (`tools.py`): `resolve_account` (domain + fuzzy name, flags AMBIGUOUS), `get_account_context` (tier, renewal, 12-mo usage trend, open escalations), `search_tickets` (BM25, account-scoped → duplicates), `get_ticket`, `search_kb` (BM25, outdated articles down-ranked + flagged), `get_kb_article` (follow `superseded_by`/policies).
`submit_triage` is validated against `schema.py`; errors go back to the model to fix. A fallback guarantees a valid file. Every tool call + observation + reasoning sentence goes in `reasoning_trace`. Ticket text is treated as untrusted (prompt-injection in TCK-9009 is ignored and noted). Providers: Grok (xAI), OpenAI, Ollama via one OpenAI-compatible client.
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

## Observed results (real run, 10 review tickets)
- 10/10 schema-valid. Tool calls per ticket: 6,5,6,3,7,5,2,6,6,5 (avg 5.1; vague TCK-9007 = 2, SSO TCK-9005 = 7) - the agent varies its path.
- Worked: vague free-mail ticket -> clarification; duplicate TCK-9003 -> TCK-8801; SSO ticket cited current KB-S01, not outdated KB-S02; injection in TCK-9009 ignored (P3, no escalation); refund request TCK-9010 cited policy KB-POL-001, no promise; security TCK-9006 -> P1 security_team, escalated.
- What failed / fixed: Groq retired llama-3.3 (switched model); free-tier 429 rate limits (added retry/backoff in llm.py); `tool_calls: null` on text-only turns caused a 400 (fixed in agent.py); observations trimmed to 2500 chars for the token limit.
- Not verified: no gold labels, so priorities (e.g. TCK-9003/9005 as P1) are judged by reading only. Runs take 15-70s per ticket due to rate limits.

## Limitations
- Not yet run on the real starter data; tests use the offline mock, which says little about LLM quality.
- Lexical retrieval only; no embeddings. Account matching is heuristic. Priority/escalation rules live in prompt + KB, not a tested rules engine. No auth on the UI; no retries/rate-limit handling for Grok free-trial limits.

## How to run
```bash
pip install -r requirements.txt
cp .env.example .env              # set XAI_API_KEY (Grok) or LLM_PROVIDER=mock
python scripts/gen_data.py        # only if data/ is missing
python run.py --set review [--provider xai]
python scripts/check_outputs.py   # 10/10 valid
python -m ui.server               # http://localhost:8000
```
