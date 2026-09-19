# Brownie

Brownie is a small, occasional browser runner. It is being built in narrow
steps so the browser boundary stays understandable.

## Current milestone: one provider-selected action

Brownie can:

- launch an isolated Chrome profile with Chrome's security sandbox required;
- open one URL;
- read visible page text and common interactive elements;
- print the resulting numbered element table; and
- optionally scroll down by one viewport and observe again; and
- read successive viewports until the bottom or a fixed limit; and
- manually execute one validated operation against a fresh viewport; and
- ask Jev for one validated operation and target without executing it; and
- execute one Jev-selected action, using a text helper only for `TYPE_TEXT`; and
- alternatively use a Gemini-compatible LLM to select the same bounded action; and
- prepare a persistent logged-in browser profile through a manual headed session.

It does not use Browser Harness or connect to the user's normal Chrome
session. Brownie owns its page observer and can evolve independently.

## Setup

From this directory:

```bash
uv sync
uv run brownie https://example.com
```

Use `--headed` to see the browser window. Brownie stores browser state in
`.browser-profile/`, which is ignored by Git:

```bash
uv run brownie --headed https://example.com
```

One explicit scroll can be requested from the command line. Brownie will not
continue scrolling by itself:

```bash
uv run brownie --scroll-down https://example.com
```

Brownie can also read through a page with a hard scroll limit. The default is
ten scrolls:

```bash
uv run brownie --read-page --max-scrolls 10 https://example.com
```

The resulting `seen_elements` are a reading summary, not executable targets.
Only elements in a fresh current-viewport observation may become targets in a
later milestone.

## One manual operation

First observe a page to see its current indexes. A second run may execute one
operation:

```bash
uv run brownie https://example.com
uv run brownie --action CLICK --target 3 https://example.com
uv run brownie --action TYPE_TEXT --target 1 --text "Baku" https://example.com
```

The supported contract is `SCROLL_DOWN`, `SCROLL_UP`, `CLICK`, `TYPE_TEXT`,
`SUBMIT`, `DONE`, and `BLOCKED`. `CLICK`, `TYPE_TEXT`, and `SUBMIT` accept only an index from the
fresh observation. Selectors, coordinates, JavaScript, and multiple actions
are not accepted. Brownie re-observes immediately before execution and rejects
the operation if the page changed. After a click, it waits up to three seconds
for a navigation destination to expose text, controls, or scrollable content.
It never repeats the click.

## Jev prediction only

Create Brownie's private environment file and add your TypeSafe key:

```bash
cp .env.example .env
```

```dotenv
TYPESAFE_API_KEY=your_key_here
TYPESAFE_MODEL=jev-latest
```

`.env` is ignored by Git. Do not commit it or paste the key into prompts or
browser pages. Ask Jev for one choice with:

```bash
uv run brownie --predict --goal "Find the pricing page" https://example.com
```

Prediction mode sends the goal, visible page text, descriptive element fields,
and offered operations to TypeSafe. It never sends Brownie's internal node IDs,
never executes the answer, and does not invoke a text-generation model.

## One provider-selected step

After prediction-only behavior is understood, Brownie can execute at most one
Jev-selected action:

```bash
uv run brownie --attach --use-open-tab --step \
  --goal "Open the listing for the off-grid Iveco motorhome" \
  https://marketplace.example/
```

The prediction is checked against a fresh observation before execution. A step
never retries a mutation and never continues into another model cycle. `CLICK`,
`TYPE_TEXT`, and one-viewport scroll operations can execute. `DONE` and
`BLOCKED` do not mutate the page.

For `TYPE_TEXT`, the steerer chooses the operation, observed field, and a typed text mode:
`SEARCH_SEED`, `FIELD_VALUE`, `IDENTIFIER`, `FREEFORM`, or `VALUE_MISSING`.
With Jev, text-mode questions for all editable fields share the same request, and code
uses only the selected field's answer. A generic catalog search therefore gets a
short subject such as `BMW X5`, not every requested filter. Only then does an
OpenAI-compatible Gemini helper receive a privacy-reduced state: the goal, mode,
selected field name/role, page title, URL without its query or fragment, other
field names with only filled/empty status, and recent operation outcomes without
typed values. It does not receive visible page text or any form values. Gemini
must return one strict JSON field value. Missing, malformed, or oversized output
changes nothing; the helper never chooses a target or browser operation.

`SUBMIT` is offered only for an observed editable field associated with a form.
It presses Enter once as its own selected operation; typing never submits
automatically. Observed links include a normalized destination and nearby
context. Numbered link groups are labeled as pagination without site-specific
rules.

Every operation report names the decision snapshot separately from the fresh
after-action snapshot. Element indexes belong only to their labeled snapshot;
the same number in a later snapshot may identify a different node.

The shared decision state keeps the immutable goal, current page and visible
text, viewport, public elements, and at most eight factual recent steps. Brownie
does not ask an LLM to maintain a free-form plan or progress summary; current
observations and recorded outcomes remain the source of truth.

## Steering boundary

Brownie's browser executor is not coupled to Jev. A steering provider returns one
`operation`, one current element `target` when required, and a bounded `text_mode`
for `TYPE_TEXT`. Code validates that result against the current observed action
space, replaces any provider-supplied target description with the observed one,
and only then permits the existing one-step executor to use it.

Jev and a Gemini-compatible LLM are connected action-steering providers. The
boundary also accepts a code-owned router selecting between providers; neither
provider gets selectors, node IDs, coordinates, or direct browser access.
There is deliberately no automatic routing heuristic yet. Candidate count alone
is not enough to choose a provider, and the policy needs evidence from actual
Brownie failures before it is made executable.

At the Python boundary, use `steer_action(observation, goal, provider="jev")`
for explicit selection. Adapters registered through `providers={name: callable}`
receive a detached public observation, the goal, and up to eight factual recent
steps. They return the same action contract; Jev probabilities and confidence
fields are optional diagnostics, not requirements for other providers.

For future automatic selection, pass `router=choose_provider` instead of
`provider`. The router receives `{"state": decision_state, "action_space": ...}`
and returns `SteeringRoute(provider="jev", reason="...")`. It runs once per
decision, selects one registered provider, and records its reason under `routing`.
Access barriers stop before routing. Invalid routes and invalid choices stop;
provider failures never switch between Jev and LLM. Within the LLM provider,
model-specific rate limits can use the configured fallback chain below. Both
providers use the same freshness check and executor.

`TYPE_TEXT` remains a separate handoff: the action steerer chooses the field and
text mode, then the text helper writes only the field value. It does not steer the
browser.

## Gemini steering and model fallback

Use one `.env` file. `GEMINI_API_KEY` supplies both Gemini roles; optional
`STEERING_MODEL_API_KEY` and `TEXT_MODEL_API_KEY` override it for their respective
roles. Existing text-helper configurations continue to work. Environment variables
already set in the shell take precedence over `.env`.

```dotenv
GEMINI_API_KEY=your_key_here
STEERING_MODEL=gemini-3.6-flash
STEERING_MODEL_FALLBACKS=gemini-3.5-flash-lite
TEXT_MODEL=gemini-3.5-flash-lite
TEXT_MODEL_FALLBACKS=gemini-3.1-flash-lite
```

Choose models available to your project. The two roles have independent ordered
model lists, but calls to the same model still consume its project quota. Both
base URLs default to Google's Gemini-compatible endpoint; `.env.example` shows
the role-specific overrides. The implementation follows Google's
[compatible API](https://ai.google.dev/gemini-api/docs/openai) and
[rate-limit documentation](https://ai.google.dev/gemini-api/docs/rate-limits).

```bash
# Inspect the LLM decision without executing or generating field text:
uv run brownie --steerer llm --predict --goal "Find the pricing page" https://example.com
# Execute at most one selected action:
uv run brownie --steerer llm --step --goal "Find the pricing page" https://example.com
```

Omitting `--steerer` keeps Jev as the default. LLM steering sends the same public
decision state (including visible text and current field values) to the configured
endpoint and requires a strict JSON operation/target/text-mode response. Field-text
generation remains a separate request with the privacy-reduced state described
above. Models never supply selectors or executable code.

Fallback policy for both Gemini roles:

- Try each distinct model at most once, with at most two fallbacks (three requests).
  No same-model retry or waiting loop is performed.
- Switch only on HTTP 429 with structured quota details identifying exclusively
  model-specific limits. Shared/spend limits and unclassified 429 errors stop;
  a bare 429 is not assumed to be model-specific.
- Save the server's retry delay, with a minimum 60-second cooldown. Daily quota
  limits cool down until at least midnight Pacific time. Cooling models are skipped.
- Cooldowns persist across CLI runs in ignored `artifacts/model-cooldowns.json`,
  containing hashed endpoint/key/model identities and expiry times only. Roles
  sharing the same endpoint and key share cooldowns. Different keys in one project
  still share Google's quota, but this local cache cannot correlate them.
- Authentication, invalid requests, network/server errors, refusals, truncated
  output, and invalid choices stop without fallback. If all models are unavailable,
  no action executes. Results record the answering model and attempted/skipped models.

All fallback happens before browser execution. Brownie rechecks observation
freshness after model calls and never repeats a browser mutation.

## Controller guards

Brownie has a code-owned controller state for the future multi-step runner. It
remembers visited page/view fingerprints, per-page scroll extents and counts,
recent factual outcomes, and observed form values even after their controls move
offscreen. It never stores executable node references as memory.

The controller stops on step/page/scroll budgets, no-effect actions, a repeated
mutation from the same observed state, or repeated action-state cycles of any
period represented in its bounded history. These guards are implemented and
tested, but they are not connected to an automatic `--run` mode yet.

## Prepare login state

Use a headed, explicitly interactive run for a site that requires login or a
human challenge:

```bash
uv run brownie --login https://marketplace.example/login
```

Complete login, MFA, “remember me,” or the challenge in Chrome. Do not close
the browser window; return to the terminal and press Enter after the destination
page is ready. Brownie then closes Chrome normally, preserving cookies and local
storage in `.browser-profile/` for later runs.

Brownie never asks for the password in the terminal and does not put credentials
in `.env`. The browser profile contains sensitive session material: keep it
private, ignored, and backed up only as securely as account credentials. The same
profile cannot be opened by simultaneous Brownie runs.

Prediction mode locally returns `BLOCKED` without calling either steerer when it sees a
visible password field, a login URL, or a Cloudflare-style challenge. Re-run
`--login` when a saved session expires.

The default `chrome` channel uses an installed Google Chrome, so Playwright
does not need to download another browser. Override it only when deliberately
testing another installed Chromium channel. Brownie requires Chromium's
security sandbox and never retries with `--no-sandbox`. If Chrome cannot start
under that constraint, the run stops before opening a page.

The sandbox removes the insecure-launch warning, but it does not guarantee that
a bot challenge will accept the automated browser. Brownie does not bypass
challenges. If manual verification keeps looping, stop the run and use the
attach mode below.

## Attach to user-launched Chrome

For challenge-protected sites, launch Chrome yourself with a dedicated profile
and a debugging endpoint bound to the local machine:

```bash
mkdir -p .browser-profile-cdp
google-chrome --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$PWD/.browser-profile-cdp"
```

In that Chrome window, open the site and complete its challenge, login, and MFA
manually. Only after the destination works normally, attach Brownie from a
second terminal:

```bash
uv run brownie --attach --use-open-tab https://marketplace.example/
```

`--use-open-tab` selects the most recently opened tab with the same web origin.
It does not navigate or close that user-owned tab. If there is no match, Brownie
stops instead of opening a new page. Without `--use-open-tab`, Brownie opens and
owns one new tab, then closes that tab when the run ends. Both modes disconnect
without closing Chrome. The dedicated Chrome profile retains cookies and local
storage for later runs.

Chrome 136 and later do not permit remote debugging of the normal default
profile, so `--user-data-dir` must point to this separate directory. Do not
expose port 9222 to another machine: while Chrome is running, a local process
that can reach the debugging endpoint can control that browser and its logged-in
sessions. Close the dedicated Chrome when it is not needed.

## Check it

The offline test opens `tests/fixture.html`; it does not contact a website or
call a model:

```bash
uv run python -m pytest
```

## Current boundary

Each observation sees only the current top-level viewport. Bounded page reading
can join observations from successive viewports, stopping at the page bottom,
a repeated view, a failed scroll, or `--max-scrolls`. It does not inspect
iframes, shadow roots, canvas content, or browser chrome. There is no general
action loop or scheduler yet. Either steerer can choose one operation with
`--step`; `TYPE_TEXT` additionally invokes the field-text helper. Login preparation is always
interactive.
