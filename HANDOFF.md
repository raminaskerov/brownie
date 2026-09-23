# Brownie continuation ledger — 2026-09-23

## Objective

Make Brownie reliable for practical browser tasks, resolving observed friction before
expanding into autonomous multistep execution. Keep Jev and an LLM interchangeable
as action steerers. The latest priority is the user's failed search-bar discovery.

## Latest update: portable Windows product-test build

- Keep one cross-platform repository. `.github/workflows/windows-build.yml`
  now tests and builds a portable `Brownie-Windows` artifact on
  `windows-latest` for each `main` push, version tag, or manual run.
- The artifact is an unsigned one-folder development build. A tester extracts
  it and double-clicks `Brownie.exe`; Python, uv, Git, and a terminal are not
  required. Installed Google Chrome is still required.
- The packaged executable starts the existing local UI and relaunches itself
  internally as the isolated CLI worker. Settings, traces, and browser profiles
  use `%LOCALAPPDATA%\Brownie` on Windows.
- The UI now saves TypeSafe and Gemini keys locally without returning them,
  reports only configured status, validates required keys before a run, and has
  a Quit Brownie control.
- Local validation: 134 offline tests, Ruff, lock check, diff check, frozen
  Linux bundle self-check, Playwright-driver startup, worker dispatch, and the
  localhost settings/status/quit flow. Native Windows artifact execution remains
  unverified until the committed workflow runs on GitHub.

## Problem formulation

The user reports asking Brownie to find a search bar: it scrolled up, then reported:

```text
Steering choice (jev): BLOCKED
Steering source: jev
```

This is a user-reported failure, not a reproduced bug. The site, exact command/goal,
decision observation, model probabilities, and after-scroll state were not supplied.
`source: jev` identifies a Jev choice, not the local access guard. `BLOCKED` is a
model-selected outcome; it does not prove that the page offers no useful action.
Do not assume the problem is fixed by switching models or changing one prompt.

## State

- Working tree contains uncommitted Windows product-build work from the latest
  update. Preserve it until reviewed and committed.
- `AGENTS.md` is the contributor guide; `README.md` documents commands and boundaries.
- `steering.py` provides public, detached observations, shared choice validation,
  explicit provider selection, and an optional `SteeringRoute` callback with a reason.
  No automatic workload-routing policy is implemented.
- CLI supports `--steerer jev|llm` with `--predict` or `--step`. Default remains Jev.
  `--predict` never executes or generates field text. `--step` executes at most one action.
- `llm_model.py` implements Gemini-compatible structured action selection.
  `model.py` remains Jev's adapter. `text_model.py` separately generates a selected
  field's value. `chat_model.py` owns shared HTTP transport and model fallback.
- Private `.env` was configured to share the existing Gemini key. Steering:
  `gemini-3.6-flash` → `gemini-3.5-flash-lite`. Text: existing
  `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite`. Do not print credentials.
  `.env.example` documents all settings and role-specific key overrides.
- Fallback tries each distinct model once, maximum three candidates, only for
  structured model-specific HTTP 429 quotas. Shared/unclassified quotas, invalid
  output, authentication, and other failures stop. Cooldowns persist in ignored
  `artifacts/model-cooldowns.json`, using hashed identities and expiry times.
  Model fallback never repeats a browser action or switches Jev to LLM automatically.
- Windows portability no longer has an import-time `fcntl` blocker: cooldown files
  use `msvcrt.locking` on Windows and `fcntl.flock` on Unix. Windows installs pull
  `tzdata`, and `.env` plus cooldown paths default to the working directory rather
  than the installed package location. `BROWNIE_RUNTIME_DIR` overrides that root.
- `controller.py` has tested budgets and cycle guards, but there is no automatic
  runner. The CLI currently calls steering without recent-step history; separate
  invocations do not retain a decision history.
- Next debugging entry: obtain the failed command, exact goal, and affected page;
  capture a prediction-only `--json` observation and decision at the failure state.
  Check whether the search control and relevant scroll operations are represented
  before changing model logic. Keep any sensitive page captures private and ignored.
  If comparing Jev and LLM, use the same captured state and goal without executing.
  Turn a confirmed failure into a small fixture/regression test, then fix that cause.

## Hypotheses / interpretations

- User's medium-term routing hypothesis: use Jev when choices overwhelm an LLM;
  use an LLM when straightforward tasks need flexible interpretation. This remains
  unvalidated; candidate count alone has not established a routing policy.
- For the reported failure, an observation gap and a poor choice despite adequate
  observation are competing explanations. Neither has been established.
- Relevant code limits, not diagnosed causes: observation covers the top-level
  viewport, caps controls at 100 and text at 6,000 characters, and does not inspect
  shadow roots or iframes. `omitted_elements` appears in raw observations but is
  not currently included in provider decision state. Fresh CLI runs omit history.

## Discarded paths

The initial new steering default `gemini-2.5-flash` was replaced after a live 404
said it was unavailable to new users, despite appearing in the models list.
The error recommended `gemini-3.6-flash`, which passed the subsequent live check.

## Tensions / unresolved questions

Provider interchangeability and passing fixture tests do not establish reliable
real-site operation. The search-bar failure remains open. The user explicitly
wants the practical frictions addressed eventually; this chat ends before diagnosis.

## Evidence / provenance

- Latest completed full offline suite: **96 passed in 10.76s**. Ruff and
  `git diff --check` passed. Tests cover provider choice, fallback/cooldown behavior,
  invalid output, and freshness checks after steering and text-model fallback.
- Live synthetic requests validated the primary LLM steerer and both configured
  backup models. No real page data was sent and no browser action executed.
  Quota exhaustion/fallback transitions were simulated offline, not induced live.
- Tests run with `.venv/bin/python -m pytest -q --tb=short`; Ruff with
  `.venv/bin/python -m ruff check .`. The local `uv` executable hit a snap confinement
  error. Chrome fixture tests required execution outside the tool sandbox while
  retaining Chrome's own security sandbox. Do not use `--no-sandbox`.
- Source of the new failure is the user's closing message quoted above, not a
  saved trace. Do not invent its URL, goal wording, or cause.

## Trajectory

Contributor guide → verify interchangeable steering before multistep work →
strengthen and test the shared boundary → connect Gemini with independent role
settings and bounded model fallback → synthetic integration checks passed →
user reports real search-bar failure → resume from evidence-driven debugging.
