# Brownie

Brownie is a small, occasional browser runner. It is being built in narrow
steps so the browser boundary stays understandable.

The product direction is one shared safe browser core with two modes: a
deterministic **basic mode** for repeatable tasks and a bounded,
conversational **research mode** with layered perception and planning. They
will not be separate forks. See [the product architecture](docs/product-architecture.md)
for the mode contracts, reliability program, and staged roadmap. The
[tool comparison](docs/tool-comparison.md) records current alternatives and
near-term adoption decisions. The [reliability matrix](docs/reliability-matrix.md) separates
repeatable fixture coverage from dated live smoke evidence.

## Current milestone: Basic workflows and bounded multi-source research

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
- prepare a persistent logged-in browser profile through a manual headed session; and
- take a goal without a URL, search DuckDuckGo, open one selected external source,
  read its page material, and stop;
- adopt a newly opened tab after a validated click or submission;
- wait for an observable navigation or same-page outcome after those operations; and
- inspect visible frame and open-shadow-root DOM surfaces while reporting any
  inaccessible frame, text-limit, and element-limit perception gaps;
- add a bounded, non-executable accessibility structure when an ordinary DOM
  observation is sparse, while suppressing that fallback on password pages; and
- plan a bounded research pass, read up to five distinct sources through the
  existing safe search runner, and return a source-linked answer or question.

It does not use Browser Harness or connect to the user's normal Chrome
session. Brownie owns its page observer and can evolve independently.

## One bounded web search

Give Brownie a research goal without supplying a URL:

```bash
./.venv/bin/brownie --managed-cdp --search --keep-open --steerer llm \
  --goal "Find the official eligibility requirements for the Erasmus Mundus scholarship"
```

`--keep-open` leaves Brownie's owned headed browser visible after the search
finishes. Return to the terminal and press Enter when you want Brownie to close
it. Without this flag, the browser closes when the command completes.

With `--managed-cdp`, Brownie starts ordinary headed Chrome with its dedicated
`.browser-profile-cdp/`, attaches through localhost, opens the code-owned
DuckDuckGo start page, and uses the same validated one-action boundary for every
step. When the start page has one unambiguous search form, code owns typing and
submission: the text helper writes a compact web query from the original goal,
then the selected steerer begins with the semantic choice among search results.
It stops after opening and reading one external source. The default limits
are eight browser actions, three distinct pages, and ten source-page scrolls;
use `--max-steps`, `--max-pages`, and `--max-scrolls` to lower them. Omit
`--managed-cdp` only when you deliberately want the original Playwright-launched
`.browser-profile/` mode.

This first search milestone does not compare sources, go back, reformulate a
query, synthesize an answer, log in, or bypass a challenge. Its returned
`source.material` is page text grounded in the selected URL; relevance still
depends on the steering model's result choice. `source.evidence_candidates`
contains up to five exact source lines ranked locally by overlap with the goal.
It does not send source material to another model or claim semantic relevance or
sufficiency.

## Bounded research mode

Research mode adds a planner above the one-source search policy. The planner can
choose the next query, answer from collected excerpts, ask the user a material
clarifying question, or stop. It never receives browser handles or proposes
selectors, JavaScript, coordinates, or executable actions.

```bash
./.venv/bin/brownie --managed-cdp --research --steerer llm \
  --max-sources 3 --goal "Compare the official eligibility rules and application deadlines"
```

The code-owned controller limits research to one through five distinct sources,
rejects an answer before the minimum evidence count, rejects duplicate queries
and sources, validates citation identifiers, and caps planner cycles. Each
source is still obtained through Brownie's existing bounded `goal -> search ->
one result -> one source -> stop` runner.

This is not yet a general autonomous researcher. It has no long-lived memory,
follow-citation tool, or contradiction engine. In the control room, the planner
can ask up to three clarification questions and continue the same run with the
same browser and collected sources. User answers clarify the research state;
they never become browser commands or new execution authority. See
[Research mode](docs/research-mode.md) for the exact boundary.

## Basic mode for repeatable tasks

Basic mode runs a validated local JSON workflow without model calls. It matches
semantic targets against every fresh observation, restricts navigation to the
contract's allowed origins, and stops instead of improvising when a target is
missing, ambiguous, unsupported, or outside Brownie's current perception.

    uv run brownie --basic-task tasks/report.json \
      --input query="solar report" \
      --headed

The first contract version supports field text, search submission, link
navigation, simple control toggles, scrolling, assertions, bounded page reading,
and explicit completion. Generic buttons and non-search form submissions remain
blocked because their consequences cannot yet be classified reliably. See
[Basic-mode task contracts](docs/basic-tasks.md) for the schema, safety boundary,
and structured stop reasons.

### Local API and other Playwright browsers

The control room also provides a tokened localhost API for starting typed runs,
polling the structured result, replying to a planner question, stopping, and
closing Brownie's owned browser. See [Local API](docs/local-api.md). Basic tasks
can capture a unique visible line, paste it into a later observed field, and
report named values with their source URLs; see [Basic-mode task contracts](docs/basic-tasks.md).

Chrome remains the default. For a Playwright-owned Firefox or WebKit session,
install that browser build and select it in the control room or pass `--browser`:

```bash
uv run python -m playwright install firefox webkit
uv run brownie --browser firefox --headed https://example.com
uv run brownie --browser webkit --read-page https://example.com
```

Each engine uses its own isolated profile. `--attach`, `--managed-cdp`, and
`--channel` apply only to Chromium. Firefox and WebKit launch paths have offline
contract tests but have not been live-tested in this checkout because their
Playwright browser builds are not installed here.

### Inspect what Brownie sent and received

Add an opt-in trace to any run:

```bash
./.venv/bin/brownie --managed-cdp --search --steerer jev \
  --trace artifacts/last-run.jsonl --goal "Find the official Python pathlib documentation"
```

Brownie writes the exact local events to `artifacts/last-run.jsonl` and a
text-only companion interface to `artifacts/last-run.html`. The interface shows
the observer output, the smaller factual state and recent-step memory actually
sent to the provider, the offered actions, exact request body without credentials,
raw response, Jev probability tables, parsed choice, freshness check, execution,
and deterministic source-reading viewports. It also separates controller memory
that was stored locally but not sent to either provider.

Tracing makes no additional model calls and includes no screenshots. It is off
by default because the files can contain sensitive page text, URLs, and entered
field values. `artifacts/` is ignored by Git.

### Local control room

Start Brownie's private local interface from the repository directory:

```bash
./.venv/bin/python -m brownie_agent.ui
```

After the next `uv sync`, the shorter `./.venv/bin/brownie-ui` entry point is
also available.

It opens `http://127.0.0.1:8766/` and provides one place to choose the current
task, Chrome start mode, Jev or LLM steering, limits, and whether Brownie's owned
Chrome stays open after the task. It shows a compact decision timeline, Brownie's
current research decision, open evidence needs, collected source links, final
grounded result, process errors, and the live `artifacts/last-run.html`
inspector. It also accepts bounded clarification answers during a research run.
Use **Close Brownie browser** when a finished managed or Playwright window should
close.

The control room keeps exact private run traces and compact decision indexes
under `artifacts/runs/` after each process finishes. Planner proposals are
recorded as proposals, not promoted to trusted facts for later runs.

The control room accepts one run at a time, binds only to localhost, and does not
offer a free-form command field. It invokes the same CLI, observer, freshness
checks, action validation, and executor as terminal runs. **Stop run** interrupts
the CLI so its browser context can clean up; it does not retry the current action.
The inspector and final reply make no additional model calls. They can contain
private page text, URLs, and typed values because the normal opt-in trace is used.

## Windows product-test build

Brownie keeps one codebase. Every push to `main` automatically runs the
offline tests on a Windows GitHub runner and produces a portable
`Brownie-Windows` artifact.

For a nontechnical tester:

1. Download the `Brownie-Windows` artifact from the latest successful
   **Windows product build** workflow run.
2. Extract the complete ZIP.
3. Double-click `Brownie.exe`.
4. If a model-powered task is needed, open **Model keys** once and paste the
   supplied TypeSafe and/or Gemini key.
5. Use **Quit Brownie** before replacing the build.

The tester does not install Python, `uv`, or Git and does not use a terminal.
Google Chrome must already be installed. This is deliberately an unsigned
portable development build rather than an installer, so Windows may show a
SmartScreen warning. Brownie stores its private settings, traces, and browser
profiles under `%LOCALAPPDATA%\Brownie`; keys and profiles are never included
in the build artifact.

## Source setup

From this directory:

```bash
uv sync
uv run brownie https://example.com
```

If `uv` resolves to `/snap/bin/uv` and Snap refuses to start because its AppArmor
service is unavailable, that failure occurs before Brownie or Chrome starts. Do
not disable Chrome's security sandbox. After the environment has already been
created with `uv sync`, invoke Brownie directly instead:

```bash
./.venv/bin/brownie --search --steerer jev --goal "Find the official Python pathlib documentation"
```

In Windows PowerShell, use `.venv\Scripts\brownie.exe` in place of
`./.venv/bin/brownie`.

Brownie's default mode uses Playwright to launch an isolated profile even if
another Chrome window is already running. For sites that distinguish that launch
from ordinary Chrome, `--managed-cdp` makes Brownie start ordinary headed Chrome
itself and then attach through localhost. An existing ordinary Chrome session
still cannot be attached after the fact unless it was started with remote
debugging enabled.

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

### Windows PowerShell

The regular `uv` commands above use the same syntax in Windows PowerShell.
Install `uv` and Google Chrome first, then run them from the repository directory:

```powershell
uv sync
uv run brownie --headed https://example.com
uv run python -m pytest
```

Bash examples in this README use `\` for line continuation. In PowerShell,
put the command on one line or use PowerShell's backtick continuation character:

```powershell
uv run brownie --attach --use-open-tab --step --goal "Open the listing for the off-grid Iveco motorhome" https://marketplace.example/
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
the operation if action-relevant structure changed. Incidental status text or
document-height churn may pass only when the URL, title, viewport position,
complete semantic target table, access signals, and perception state remain
identical. After a click, it waits up to three seconds for a navigation
destination to expose text, controls, or scrollable content. It never repeats
the click.

## Jev prediction only

Create Brownie's private environment file and add your TypeSafe key:

```bash
cp .env.example .env
```

In Windows PowerShell:

```powershell
Copy-Item .env.example .env
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

By default, Brownie reads `.env` and stores `artifacts/model-cooldowns.json`
relative to the current working directory, not relative to the installed Python
package. Set `BROWNIE_RUNTIME_DIR` to use one explicit private runtime directory
for both paths. Set that variable in the shell or process environment because it
must be known before Brownie can locate `.env`.

Prediction mode sends the goal, visible page text, compact complete moves, and
only non-empty descriptive target fields to TypeSafe. A complete move combines
an operation with its current target, replacing separate operation/click/type/
submit questions. Editable fields still receive a bounded value-shape question.
It never sends Brownie's internal node IDs,
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
  still share Google's quota, but this local cache cannot correlate them. File
  locking uses the native Windows or Unix mechanism.
- Authentication, invalid requests, network/server errors, refusals, truncated
  output, and invalid choices stop without fallback. If all models are unavailable,
  no action executes. Results record the answering model and attempted/skipped models.

All fallback happens before browser execution. Brownie rechecks observation
freshness after model calls and never repeats a browser mutation.

## Controller guards

Brownie's bounded automatic search runner uses a code-owned controller state. It
remembers visited page/view fingerprints, per-page scroll extents and counts,
recent factual outcomes, and observed form values even after their controls move
offscreen. It never stores executable node references as memory.

The controller stops on step/page budgets, no-effect actions, a repeated
mutation from the same observed state, or repeated action-state cycles of any
period represented in its bounded history. A per-page scroll limit rejects only
a later scroll action; reaching it cannot stop typing, submitting, or clicking.
These guards are implemented and tested in the bounded search runner.

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

### Brownie-managed Chrome (recommended for search)

Let Brownie perform the same launch-and-attach sequence automatically:

```bash
./.venv/bin/brownie --managed-cdp --search --keep-open --steerer jev \
  --goal "Find the official Python pathlib documentation"
```

This starts ordinary headed Chrome with only the local debugging address, port,
and dedicated profile arguments, waits for it to become ready, then attaches
Playwright. Brownie uses `.browser-profile-cdp/` by default in this mode. It
disconnects and closes only the Chrome process it started when the run ends;
`--keep-open` waits for Enter first. If port 9222 already belongs to a debugging
session, Brownie stops and tells you to use `--attach` rather than silently taking
over that browser. Use `--chrome-executable /full/path/to/chrome` if automatic
Chrome discovery fails. A separately running normal Chrome is not reused or
closed; managed mode opens its own window and dedicated profile.

Managed CDP removes Playwright's browser-launch defaults; it does not make the
session undetectable, bypass a challenge, or guarantee that a site will preserve
access. The observer and actions are still browser automation after attachment.

### Manual launch and attach

For challenge-protected sites, launch Chrome yourself with a dedicated profile
and a debugging endpoint bound to the local machine:

```bash
mkdir -p .browser-profile-cdp
google-chrome --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port=9222 \
  --user-data-dir="$PWD/.browser-profile-cdp"
```

In Windows PowerShell, the equivalent for Chrome installed in its default
system-wide location is:

```powershell
New-Item -ItemType Directory -Force .browser-profile-cdp | Out-Null
$profile = (Resolve-Path .browser-profile-cdp).Path
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 "--user-data-dir=$profile"
```

If Chrome is installed elsewhere, replace the executable path. Keep Brownie
and the Chrome debugging session in the same operating-system environment;
attaching from WSL to Windows Chrome is not a documented setup.

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

Each observation is bounded to visible DOM text and controls in the current
viewport, including inspected frames and open shadow roots. Sparse pages may add
non-executable accessibility structure. Closed shadow roots, canvas-only content,
and browser chrome remain outside this view. Bounded page reading joins
successive viewports; search and research use code-owned action and source
budgets. Either steerer can choose one operation with `--step`; `TYPE_TEXT`
additionally invokes the field-text helper. Login preparation remains
interactive. There is no scheduler or general cross-site workflow planner.
