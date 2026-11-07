# Aureon AI architecture

Aureon AI is compulsory in the customer product and is not a switch. Customers do not install a model, see an endpoint, or enable AI. The previous local Ollama path remains in the repository for the existing private tests. The customer shell does not ask it whether to show an analysis.

## Provider

[ops/hosted_ai.py](/tmp/aureon-experience/ops/hosted_ai.py) is the adapter. A call is allowed only when all of these are set on the server:

- `AUREON_AI_API_KEY`
- `AUREON_AI_BASE_URL` starting with `https://`
- `AUREON_AI_MODEL`
- `AUREON_AI_SPEND_APPROVED=1`

If any one is missing, `operational` is `BLOCKED`, `reason` is `provider_not_configured`, `analysis` is null, and `urllib` is not called. The response includes the authorised stored facts labelled `stored_record_not_an_analysis`. That is not a substitute model reply.

The product route `POST /api/aureon-ai` never passes a transport. Tests may inject one. A configured route that cannot reach the provider returns `provider_unavailable` and still does not invent an analysis. Timeout is 8 seconds. Retries are 0, so a failure cannot double-charge. Prompt version is `aureon-hosted-1`.

Usage counters in the response are process memory only (`durable_billing: false`). A durable cost ledger is NOT IMPLEMENTED. No key is written to the activity log. The log event is `hosted_ai_request` with page, called flag, operational state, and reason.

Live provider operation: **BLOCKED**. This environment has no approved key or spend approval. No real model was called. Do not treat the architecture as an operational model.

## Evidence

Before any provider call, `ops/ai_evidence.build` loads the signed-in account's stored observations, paper counts, persona, and task facts. The model is not allowed to choose its own permissions. Page-to-task mapping lives in `PAGE_TASK` (overview and portfolio, terminal market watch, scanner and inbox why-quiet, signals explain, research and strategies research, plan and risk and settings risk, orders and history and lab journal, academy academy).

The customer shell posts `{page, question}` from the header panel and from the Live Signals card. The same route serves every page. The page name selects the task.

## Refusal rules

| Case | Result |
| --- | --- |
| Question asks to place a trade or approve a strategy | `order_request_refused`. No model call. |
| Question contains another account id, or another account name of at least four characters | `other_account_refused`. Stored facts are not returned. |
| Summary contains order language, including a hidden character, spaced letters, a digit used as a letter, or the word purchase, or a number that was not in the facts, including a short digit run, a spelled number, or a Roman numeral | `invalid_output`. `analysis` stays null. |
| Summary contains another account id or name, or a hyphenated identifier that is not in the facts or refs, including a spaced or possessive form | `invalid_output`. |
| `evidence_used` cites text that is not in the facts or refs | `invalid_output`. |
| Valid summary | `ai_commentary_not_a_signal`. `approved` and `order_opened` are forced false. |

The signal engine does not import `hosted_ai` or `ollama`. Signal generation does not wait on the model.

## Customer behaviour when blocked

The header control still opens Aureon AI. The panel shows the blocked note and, on a question, the stored record labelled as not an analysis. System Status says the hosted service state and that local AI status is separate from the customer desk. There is no enable checkbox.

## What remains external

Owner approval of a provider, an HTTPS base URL, a model name, a key kept outside git, and `AUREON_AI_SPEND_APPROVED=1`. Until those exist, live AI is BLOCKED. A mock reply must not be shipped as success.
