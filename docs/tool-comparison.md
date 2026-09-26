# Browser tool comparison and near-term decisions

Review date: 2026-09-26. This compares public capabilities and Brownie's tested
contract, not measured success rates or prices. A claim that Brownie is generally
better or cheaper for basic automation would be false. A maintained Playwright
script is usually the simplest and cheapest way to run a known, stable workflow;
Brownie adds a constrained task format, fresh-observation checks, structured
stops, and a local control room at the cost of a smaller action set.

| Tool | What it already offers | Brownie decision |
| --- | --- | --- |
| [Playwright](https://playwright.dev/python/docs/intro) | Cross-browser automation, semantic locators, tracing, mature input APIs | Keep the foundation. Add opt-in Firefox and WebKit launch paths; use Playwright primitives where a captured failure requires them. |
| [agent-browser](https://github.com/vercel-labs/agent-browser) | Compact accessibility snapshots, refs, text extraction, screenshots, persistent sessions, a CLI | It has a broader manual/agent tool surface than Brownie. Brownie now captures and reports named visible values for Basic tasks. Do not replace Brownie's validated executor with arbitrary selectors or JS. |
| [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Accessibility snapshots and many browser tools usable by an external agent | Useful as a baseline for generic exploration. Brownie's smaller closed action contract remains useful for unattended, audited tasks. |
| [Browser Use](https://github.com/browser-use/browser-use) | General multi-step agent, human-help tools, structured results, local or hosted browsers | Its general task coverage is ahead of Brownie's. Borrow bounded user return and structured results; keep deterministic Basic tasks model-free. |
| [Stagehand](https://github.com/browserbase/stagehand) | `act`, `extract`, `observe`, and a full agent path; repeatable actions can be cached | The code-first / AI-when-needed split fits Brownie's two modes. Avoid importing its broader action path without Brownie's validation. |
| [Skyvern](https://github.com/Skyvern-AI/skyvern) | Form-heavy workflows, validation and extraction, cloud browsers | A serious alternative for complex business process automation. Replacing Brownie now would add a large service surface without proving the user's local workflows improve. |
| [Mobile Jev](https://github.com/droidrun/mobile-jev) | Android device runner through Mobilerun with Jev steering | Separate runtime and device access. Reuse only the principle of one observed action and bounded control; no Android claim for Brownie yet. |

## Decisions against the short and medium term note

- **Copy, paste, reporting:** implemented as `CAPTURE_TEXT`, later `TYPE_TEXT`
  from a named capture, and source-linked captured values in Basic results.
  This stays within visible text and does not use the system clipboard.
- **Planner dialogue:** already implemented in Research mode with Gemini for
  planning and optionally LLM steering, plus bounded same-run questions in the
  control room. The planner proposes search queries, answers, questions, or stop;
  it does not directly select raw browser actions.
- **API:** existing localhost run/state/stop/reply routes now publish a private
  token file and structured result for programmatic use. See [Local API](local-api.md).
- **Other browsers:** opt-in Firefox and WebKit launch paths added. Their browser
  builds are absent locally, so only launch-contract tests have run.
- **Information foraging:** useful lens for deciding whether a source is worth
  opening and when another query has low expected value. The current evidence
  needs and source budget are a first approximation. An automatic scent score
  would be unjustified without traces showing poor result choice or wasted
  searches; compare source relevance and cost on a fixed task set first.
- **Memory:** the factual ResearchState is compact within a run. The control
  room now archives each completed run's exact private trace and a small index
  of run status and planner proposals under `artifacts/runs/`. That gives full
  remembrance and a navigable decision record without treating model proposals
  as accepted facts. Runs still cannot resume after restart. A future reusable
  memory ledger needs an explicit distinction between source claims, model
  inference, and user-accepted decisions before it can steer future runs.
- **Artificial delays:** Playwright supports per-key delays and mouse timing,
  but adding human-like delays globally has no observed benefit here. Time and
  failure rates should be measured on the affected site before adding one.
- **Press and hold:** Playwright exposes mouse down/up and gesture durations.
  Brownie needs a captured Sahibinden state and a classified hold target before
  exposing a validated `PRESS_HOLD` action; duration must be bounded and mouse-up
  guaranteed even on failure.
- **Android:** Mobile Jev is a separate device stack, not a browser backend.
  Treat a Brownie Android mode as a later product decision after a concrete
  mobile-only task justifies it.
- **Receiving input during a run:** bounded planner clarification exists. A
  general mid-run goal change, approval, or pause/resume needs serialized run
  state and explicit authority; a free-form message cannot become a browser
  command.

## Evidence needed before a general superiority claim

Use a fixed set of ordinary tasks and compare Brownie Basic, a direct Playwright
script, agent-browser, and Browser Use on completed outcomes, false success,
safe stops, model calls/tokens, elapsed time, and setup effort. Include page
changes, ambiguous controls, and copy/report workflows. Public feature lists
cannot establish that Brownie is faster, cheaper, or more reliable on those tasks.
