# Brownie product architecture

Status: working direction, 2026-09-25

## Decision

Brownie will remain one codebase and one validated browser executor with two operating modes:

- **Basic mode** runs explicit, repeatable workflows with deterministic steps, bounded inputs, and checked outcomes.
- **Research mode** uses layered perception and bounded planning to investigate a goal, collect source-grounded evidence, and converse with the user through the local UI.

These are modes, not forks and not separate safety boundaries. A planner may propose a next intent, but it cannot execute selectors, coordinates, JavaScript, or an unvalidated action. Every browser mutation must still pass through the same fresh-observation validation and one-action executor.

## Why this split

Repetitive work and open-ended research have different failure modes.

Basic work should become cheaper and more predictable after a workflow is understood. It needs input schemas, reusable steps, postconditions, and a clear stop when the page no longer matches the workflow. It should not spend model calls rediscovering a known path.

Research work must handle unfamiliar pages, revise its approach, decide whether evidence is sufficient, and explain what it is doing. It needs planning and dialogue, but that reasoning must remain advisory to the code-owned browser boundary.

The shared core is where cross-site reliability belongs. Popup handling, readiness detection, frames, shadow DOM, downloads, access barriers, action evidence, traces, and loop guards must not diverge by mode.

## Target shape

The local UI and CLI feed either a basic task contract or a research goal and dialogue. The basic workflow runner and research controller each produce an intent or action proposal. That proposal passes through the shared policy boundary, fresh observation and validation, and the one-operation executor before Playwright can affect Chrome. Both modes write the same factual trace and consume the same layered perception snapshots.

### Shared core

The shared core owns facts and effects:

- browser and profile lifecycle;
- page, tab, popup, frame, and download events;
- layered perception snapshots;
- current executable action space;
- stale-observation and access checks;
- one validated operation at a time;
- action outcome evidence and deterministic budgets;
- private traces and replayable fixture cases.

Freshness has two code-owned levels. Exact freshness compares the complete
observation. Action-structural freshness is available only for targeted actions
and excludes incidental visible-text and document-height churn; it still hashes
the URL, title, viewport position, complete target table including values and
destinations, access signals, perception state, and scrolling availability.
Neither level retries a browser mutation.

No model owns selectors, browser handles, credentials, retry policy, or mutation recovery.

### Basic mode

A basic task is a versioned contract, not a natural-language prompt saved as a macro. A contract should eventually contain:

- named inputs and their types;
- allowed starting domains and expected page identity;
- semantic steps expressed against fresh observed roles, names, and context;
- success and failure postconditions;
- read-only versus mutating classification;
- confirmation gates for consequential writes;
- a small execution budget and an explicit return value.

The first execution can use assisted discovery. Once accepted, replay should prefer code-owned semantic matching and invoke AI only when the contract explicitly permits escalation. A mismatch pauses the workflow; it does not silently improvise or retry a mutation.

### Research mode

Research mode adds reasoning without bypassing the core:

1. Turn the user's goal into a small, inspectable research state: question, constraints, known facts, open evidence needs, and stop conditions.
2. Choose the next bounded intent, such as search, inspect source, follow a cited document, ask the user, or stop.
3. Use the existing steering seam to propose one action from the current executable action space.
4. Record the observed outcome, update factual state, and replan only when evidence or failure requires it.
5. Return claims with source passages and distinguish relevance, credibility, and sufficiency.

The plan is disposable guidance. Observations, action outcomes, source material, and user messages remain the authoritative state.

The first research expansion should be bounded multi-source comparison, not unrestricted browsing: one question, a small source budget, explicit source-selection reasons, contradiction tracking, and a stop when the evidence contract is met or cannot be met.

### Conversational UI

The current control room should evolve into a run conversation rather than a free-form remote shell. The UI needs:

- a mode selector and mode-specific task form;
- a message stream for Brownie's factual progress and user answers;
- pause, resume, stop, and approve or reject controls;
- a compact current plan with completed and open evidence needs;
- the existing exact trace inspector kept separate from the friendly conversation;
- explicit prompts when login, a challenge, missing data, or consequential action needs the user.

User messages can change the goal or answer a requested question. They never become browser commands directly.

## Layered perception

Brownie's current viewport DOM observation is a good safe first layer, but it is not enough for varied websites. Perception should grow in layers so the cheap path stays cheap:

1. **DOM viewport layer:** current text, roles, accessible names, values, destinations, and actionability.
2. **Browser event layer:** active tab, popups, downloads, navigation, dialogs, page errors, and readiness evidence.
3. **Structural layer:** frames, open shadow roots, landmarks, headings, lists, tables, and omitted-content diagnostics.
4. **Accessibility layer:** a compact accessibility snapshot when the DOM layer is incomplete or ambiguous.
5. **Visual layer:** screenshot plus element boxes only when structure cannot explain the page or a visual task requires it.

The controller should know which layers were available and what was omitted. It should not treat a sparse DOM observation as proof that no action exists.

## Reliability program

Reliability must be measured from captured failures, not inferred from a larger prompt. Every failed live run should reduce to a fixture or trace case with one primary category:

- perception gap;
- target ambiguity;
- stale or moving page;
- popup, tab, or frame transition;
- readiness or hydration delay;
- access, login, or challenge;
- unsupported operation;
- steering error;
- text-generation error;
- controller loop or budget stop;
- evidence insufficiency;
- platform or browser lifecycle failure.

The regression corpus should report per-mode task success, safe-stop rate, false-success rate, model calls, steps, and elapsed time. A change is not a reliability improvement if it only increases completion claims while increasing unsafe or ungrounded outcomes.

## What to reuse

The useful lesson from adjacent projects is component separation, not wholesale adoption.

| Project or tool | Useful part for Brownie | Decision |
| --- | --- | --- |
| [Playwright](https://playwright.dev/) | actionability, user-facing locators, popup, frame, and download events, tracing | Keep as the browser foundation and use more of its event and readiness primitives. |
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) | combined DOM, accessibility, and screenshot observations; reproducible task environments; trace-based evaluation | Borrow observation and evaluation patterns; do not add its benchmark stack to the runtime. |
| [AgentLab](https://github.com/ServiceNow/AgentLab) | reproducible experiments and trace analysis | Use as an evaluation reference, not a product dependency. |
| [Browser Use](https://github.com/browser-use/browser-use) | typed action results, bounded history, loop and stagnation detection, plans that replan on stalls, human-help tools | Borrow small patterns only. Its general agent service is much larger and permits a broader tool surface than Brownie's boundary. |
| [Stagehand](https://github.com/browserbase/stagehand) | explicit choice between deterministic code and AI, cached repeatable actions, AI fallback after a known action fails | Adopt the deterministic-first product idea, but keep Brownie's own validated action contract. |
| [Skyvern](https://github.com/Skyvern-AI/skyvern) | task and output schemas, page validation, workflow composition, visual fallback | Ideas only. The runtime is substantially heavier and AGPL-licensed. |
| [RPA Framework](https://github.com/robocorp/rpaframework) and Robot Framework | task and work-item contracts, mature non-AI automation primitives, assistant and human-input patterns | Borrow contract and orchestration concepts; do not add the broad dependency bundle now. |
| Selenium Page Objects | isolate stable site-specific services from task logic | Use only when Brownie deliberately promotes a repeated workflow to a maintained site adapter. |

## What not to import

- Arbitrary model-generated JavaScript, Python, selectors, XPath, or coordinates.
- Multi-action model batches that continue after the page changes.
- Automatic retries of clicks, submissions, purchases, messages, or other mutations.
- CAPTCHA bypass or stealth as a reliability feature.
- A model-authored progress summary as canonical run state.
- A large agent framework before Brownie's own failure corpus shows which missing component it would solve.

## Staged roadmap

Each stage must pass offline fixtures, Ruff, and focused live trials before the next stage broadens autonomy.

### Stage 1: shared-core reliability

- handle popups and new tabs without losing the active task page;
- replace generic readiness with observable action-outcome settling;
- expose perception omissions and frame or shadow presence;
- add fixtures for popup, delayed same-page update, frame, shadow DOM, dialog, and download boundaries;
- turn representative live failures into a small regression matrix.

### Stage 2: basic mode contract

- define a small JSON task contract and validator;
- support deterministic observe, choose-semantic-target, type, submit, click, read, assert, and stop steps;
- make mutation confirmation and domain allowlists code-owned;
- save accepted workflows separately from private run inputs and browser profiles;
- stop with a structured mismatch instead of improvising.

Current Basic-mode implementation: the version-1 contract, strict parser, CLI
inputs, semantic fresh-observation matching, origin allowlists, bounded safe
operation subset, structured stops, and fixture coverage exist. Saved
workflow selection and confirmed expansion to broader actions remain open. The
local UI can already launch a task path with validated inputs.

### Stage 3: perception escalation

- add frame and open-shadow-root observations without exposing executable selectors;
- add compact accessibility snapshots for ambiguous or sparse pages;
- add opt-in screenshots and element boxes for visual tasks;
- choose escalation from observable perception gaps, not from a blanket vision setting.

Current structural implementation inspects visible Playwright frames, traverses
open shadow roots, merges their text and semantic controls into one bounded
observation, and maps executable node IDs back to their owning frame without
exposing selectors. It also propagates framed login detection. Sparse pages get
a bounded, non-executable ARIA structure after editable values and link targets
are removed; pages containing password fields never enter that fallback. Closed
shadow roots, visual fallback, frame-local scrolling, and a larger real-site
regression corpus remain open.

### Stage 4: bounded research controller

- add research state and a planner proposal schema;
- support a small multi-source evidence budget;
- separate source selection, extraction, claim support, contradiction, and sufficiency;
- retain the current one-source search as the simplest research policy;
- require a user return for access barriers, consequential actions, or material goal changes.

Current Research-mode implementation: a strict planner schema, compact factual
state, one-to-five-source budget, duplicate-query and duplicate-source guards,
minimum evidence count, citation-marker validation, planner-cycle limit, CLI
entry point, bounded same-run clarification dialogue, and control-room output
exist. Source credibility comparison, contradiction tracking, citation-following,
and restartable serialized dialogue remain open. The planner has no direct
browser authority; each source still uses the shared bounded search runner and
executor.

### Stage 5: conversational control room

- add run-scoped messages and user-return requests;
- show plan and evidence state without hiding the exact trace;
- support pause and resume with serializable factual state;
- expose saved basic workflows and research runs through the same UI.

Current control-room implementation displays the latest plan, evidence needs,
source budget and collected source links; it can display a pending planner
question, accept one bounded user message over the existing process channel,
and resume the same research state. Exact source excerpts and dialogue remain in
the private trace. Persistent conversations, restart recovery, and approval
controls remain open.

## Completed foundation and next order

The first shared-core changes and the initial Basic and Research contracts now
exist:

1. popup and new-tab adoption and cleanup;
2. action-outcome settling for navigation and same-page updates;
3. perception diagnostics for frames, shadow roots, and truncation;
4. a small local reliability fixture matrix;
5. versioned Basic task contracts; and
6. a bounded research planner schema and multi-source controller.

The next order is driven by captured failures: a cross-site trace regression
matrix, frame-local scrolling, visual escalation for genuinely visual tasks,
then persistent run recovery and explicit human gates.
