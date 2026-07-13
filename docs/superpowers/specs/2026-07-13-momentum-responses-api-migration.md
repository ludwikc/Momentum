# Momentum → OpenAI Responses API migration

**Status:** proposed · **Scope:** `cogs/przywolanie.py` chat calls only · **Goal:** cut latency of
Momentum's *general/coaching replies* (not the meeting-transcript path).

## Context — why

A Momentum summon can make several **sequential** `gpt-5.2` calls. On Chat Completions every
round **resends the whole growing message list** and the reasoning model **re-reasons from
scratch** each time. `reasoning_effort="low"` (already shipped, commit `049f925`) cut the
per-call thinking; this migration attacks the **multi-round overhead** that dominates the replies
the user actually cares about — KB-grounded advice and `/coaching-momentum`, where the flow is
`round1 (model calls szukaj_w_bazie) → embedding + Supabase → round2 (answer)`.

Why the Responses API:
- **`previous_response_id` chains turns server-side.** After a tool result, the follow-up call
  sends only the tool output + the previous id — the model reuses the prior turn's reasoning/
  context instead of re-sending and re-reasoning it. Fewer input+reasoning tokens, higher prompt-
  cache hits → **lower latency across the tool loop.**
- Reasoning models get first-class tool-calling on Responses (GPT‑5.4+ restricts tool-calling with
  `reasoning:none` on Chat Completions).
- Chat Completions is on OpenAI's deprecation path.

**Non-goals:** `transcribe.py` summaries (batch, not latency-sensitive); persona/tool behaviour
(unchanged); the `szukaj_w_bazie` *embeddings* call and `transcripts.py`/`db.py` (unchanged).

## Current vs target (shape of the change)

```python
# NOW (Chat Completions) — round 2 resends the full, growing `messages` list
resp = client.chat.completions.create(
    model=MODEL, messages=messages,          # system+user+assistant tool_call+tool result+…
    tools=_TOOLS,                            # nested: {"type":"function","function":{...}}
    temperature=0.8, max_tokens=cap, tool_choice=...,
)
msg = resp.choices[0].message
if not msg.tool_calls:
    return (msg.content or "").strip()
# append assistant.tool_calls + each tool result to `messages`; loop resends everything

# TARGET (Responses) — round 2 sends only the tool outputs + previous_response_id
resp = client.responses.create(
    model=MODEL, instructions=SYSTEM_PROMPT, input=user_msg,
    tools=_TOOLS_FLAT,                       # flat: {"type":"function","name","description","parameters"}
    reasoning={"effort": MOMENTUM_REASONING_EFFORT},
    max_output_tokens=cap, tool_choice=..., store=True,
)
calls = [o for o in resp.output if o.type == "function_call"]
if not calls:
    return (resp.output_text or "").strip()
outs = [
    {"type": "function_call_output", "call_id": c.call_id,
     "output": _run_tool(c.name, json.loads(c.arguments or "{}"))}
    for c in calls
]
resp = client.responses.create(
    model=MODEL, instructions=SYSTEM_PROMPT,     # instructions do NOT carry over — resend
    previous_response_id=resp.id, input=outs,
    tools=_TOOLS_FLAT, reasoning={"effort": MOMENTUM_REASONING_EFFORT}, max_output_tokens=cap,
)
```

## Changes

1. **SDK**: bump `openai` in `requirements.txt` to a version exposing `client.responses` +
   `reasoning` + `previous_response_id`; verify at import.
2. **`_TOOLS` → flat Responses shape** (drop the nested `"function"` wrapper). The KB tool stays
   gated on `MOMENTUM_KB_ENABLED`.
3. **Replace `_create_completion`/`_chat`** with a `_respond(...)` wrapper over
   `client.responses.create(...)` — passes `instructions`, `input`, `tools`, `reasoning`,
   `max_output_tokens`, optional `tool_choice`, `previous_response_id`, `store=True`. Keep the
   **reasoning-effort auto-disable guard** (drop the `reasoning` arg if the model rejects it).
   The `max_tokens`↔`max_completion_tokens` fallback becomes moot (Responses uses
   `max_output_tokens`) and `temperature` is dropped (reasoning models) — simplify accordingly.
4. **Rewrite `_generate_reply`'s tool loop** to the `previous_response_id` pattern above:
   first call carries `instructions` (SYSTEM_PROMPT + "Dzisiaj jest …" + COACHING_INSTRUCTION when
   coaching) and `input=user_msg`; subsequent rounds send only `function_call_output` items +
   `previous_response_id`, re-passing `instructions`/`tools`/`reasoning`. Final text via
   `resp.output_text`. Keep `MOMENTUM_TOOL_ROUNDS`, the coaching `tool_choice`-forced KB lookup,
   the token caps, and the `[CISZA]` handling.
5. **`store=True`** is required for `previous_response_id`. Privacy note: OpenAI stores responses
   ~30 days. If unacceptable, use `store=False` + `include=["reasoning.encrypted_content"]` and
   resend `resp.output` items instead of the id (stateless CoT reuse) — slightly more payload.

## Latency expectation
- **Advice / `/coaching-momentum` (multi-round, KB-grounded)** — the target: round 2+ stops
  resending & re-reasoning the whole context → meaningfully faster.
- **Casual single-call chat** — already fast after `reasoning_effort=low`; modest extra win from
  prompt caching.
- Meeting-transcript answers also benefit (the ≤80k-char transcript isn't re-sent each round), but
  that's secondary per the user.

## Risks & mitigations
- **Behavioural drift** → ship behind a config flag **`MOMENTUM_USE_RESPONSES`** (default `False`):
  keep the Chat Completions path as fallback, branch in `_generate_reply`, validate live, then flip
  and delete the old path.
- **Output-item field names** (`call_id` vs `id`) → echo `call_id`.
- **SDK drift / unknown params** → pin a known-good `openai`; keep the reasoning auto-disable guard.
- **Parity** → persona, tools, limits, `[CISZA]` unchanged; only the transport changes.

## Testing (TDD where it's pure)
- Extract the one genuinely pure bit — `extract_tool_calls(output_items)` and the
  `function_call_output` builder — into `summon.py` and unit-test in `summon_test.py` with fake
  items. The network loop stays I/O (same as today).
- Manual Discord parity run: the 5 brief acceptance criteria + a coaching summon, comparing the
  existing `Momentum odpowiedział w X.Xs` / `tool-loop runda k/4` logs before vs after.
- Keep `summon_test.py` green.

## Rollout
1. Branch; bump `openai`; add `MOMENTUM_USE_RESPONSES=False`.
2. Implement the Responses path beside the current one (flag-gated in `_generate_reply`).
3. Deploy; flip the flag owner-only; compare the timing logs on real summons.
4. Flip on for everyone; after a few days delete the Chat Completions path + the now-moot
   `max_tokens`/`temperature` fallback.

## Effort
~half a day — mostly the `_generate_reply`/`_chat` rewrite + tool-shape change + the flag. Low risk
thanks to the flag and the timing logs already in place.

## Sources
- [Migrate to the Responses API](https://developers.openai.com/api/docs/guides/migrate-to-responses)
- [Conversation state / `previous_response_id`](https://developers.openai.com/api/docs/guides/conversation-state)
- [Reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
