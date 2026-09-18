# Brownie

Brownie is a small, occasional browser runner. It is being built in narrow
steps so the browser boundary stays understandable.

## Current milestone: one Jev-driven action

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
`DONE`, and `BLOCKED`. `CLICK` and `TYPE_TEXT` accept only an index from the
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

## One Jev-driven step

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

For `TYPE_TEXT`, Jev chooses the operation and observed field. Only then does an
OpenAI-compatible Gemini helper receive a privacy-reduced state: the goal,
selected field name/role, page title, URL without its query or fragment, other
field names with only filled/empty status, and recent operation outcomes without
typed values. It does not receive visible page text or any form values. Gemini
must return one strict JSON field value. Missing, malformed, or oversized output
changes nothing; the helper never chooses a target or browser operation.

The richer Jev decision state keeps the immutable goal, current page and visible
text, viewport, public elements, and at most eight factual recent steps. Brownie
does not ask an LLM to maintain a free-form plan or progress summary; current
observations and recorded outcomes remain the source of truth.

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

Prediction mode locally returns `BLOCKED` without calling Jev when it sees a
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
action loop or scheduler yet. Jev can choose and execute one operation with
`--step`; only `TYPE_TEXT` invokes Gemini. Login preparation is always
interactive.
