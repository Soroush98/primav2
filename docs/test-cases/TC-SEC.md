# TC-SEC — SQL guard, prompt injection & log privacy

Automation: [backend/tests/test_security.py](../../backend/tests/test_security.py)
(+ `test_sql_guard_rejects_writes` in test_agent.py). All run in CI.
These cases enforce the controls documented in [SECURITY.md](../../SECURITY.md);
priority follows risk R1 (the system's top risk).

| ID | Title | Req | Pri | Given / When / Then | Automation |
|----|-------|-----|-----|---------------------|------------|
| TC-SEC-01 | Guard rejects the injection corpus | REQ-03 | P1 | Given each abuse payload (DDL, DML, stacked queries, CTE-wrapped writes, EXPORT exfil, comment-prefixed) / When passed to `assert_read_only` / Then ValueError — extend the corpus whenever a new probe appears in the logs | `test_guard_rejects_injection_corpus` |
| TC-SEC-02 | Guard passes legitimate analyst SQL | REQ-03 | P1 | Given real SELECT/WITH shapes incl. keyword-substring identifiers (`update_time`) / When validated / Then accepted — the guard must not break the product | `test_guard_allows_legitimate_reads` |
| TC-SEC-03 | Cross-project table refs rejected | REQ-03 | P1 | Given SQL referencing `other-project.dataset.table` / When checked by `assert_tables_in_project` / Then rejected (exfil via credentials' broader access) | `test_cross_project_reference_rejected` |
| TC-SEC-04 | Mixed project refs rejected | REQ-03 | P1 | Given one allowed table JOINed to a foreign-project table / When checked / Then rejected — an allowed ref must not smuggle another in | `test_mixed_project_references_rejected` |
| TC-SEC-05 | Injected agent run fails safe end-to-end | REQ-03 | P1 | Given an LLM coaxed into emitting `DROP TABLE` / When the full graph runs / Then the runner is never invoked, `error` is recorded, and the user still gets a coherent briefing — fail-safe, not fail-crash | `test_prompt_injected_sql_never_reaches_the_warehouse` |
| TC-SEC-06 | Search log is one parseable JSON line | REQ-06 | P2 | Given a search / When logged / Then exactly one stdout line of valid JSON with the documented fields (Cloud Logging contract) | `test_search_log_is_one_parseable_json_line` |
| TC-SEC-07 | Log bounds hostile input | REQ-06 | P2 | Given a 50k-char question / When logged / Then truncated to 2000 chars — log pipeline can't be bloated | `test_search_log_caps_pathological_question_length` |
| TC-SEC-08 | Log carries no credentials | REQ-06 | P1 | Given any search / When logged / Then fields are exactly {severity, event, question, detector, client_ip} — no headers, no key material | `test_search_log_never_contains_credentials` |

**Related exploratory charter** (QA-STRATEGY §8.1): actively probe the guard with
jailbreak phrasings against the live agent; every SQL shape it emits that gets
rejected joins the TC-SEC-01 corpus as a permanent regression input.
