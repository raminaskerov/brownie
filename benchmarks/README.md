# Local Basic baseline

Run a fixed, model-free comparison against a direct Playwright script:

    .venv/bin/python benchmarks/compare_basic.py --repetitions 3 \
      --output artifacts/basic-comparison.json

The four local Chrome cases are capture-and-paste, search submission, delayed
navigation, and an ambiguous textbox that should stop safely. Each run uses a
fresh persistent profile, Chrome's security sandbox, and the same local fixture.
Order alternates by repetition. The script verifies the final page state or
safe stop and records elapsed time from browser startup through context close.
Both paths make zero model calls.

This is a narrow engineering baseline. The direct Playwright path is a
maintained script written for these exact pages; Brownie Basic adds a reusable
JSON contract, observation, action checks, structured stops, and tracing.
These fixtures do not establish performance on changing public sites or
measure authoring and maintenance time. Compare external tools on the same
tasks and expected outcomes before making a general reliability or cost claim.

## Same-page comparison with agent-browser

The second script serves the capture fixture itself over localhost and compares
three model-free paths with a fresh Chrome profile per run. It verifies the
textbox value and includes browser close in each timing:

    .venv/bin/python benchmarks/compare_capture_tools.py --repetitions 3 \
      --agent-browser-binary /path/to/agent-browser-linux-x64 \
      --output artifacts/capture-tools-comparison.json

The optional agent-browser binary came from agent-browser 0.38.1. It uses the
CLI's snapshot ref for the textbox and its own text/value commands. The script
passes no sandbox-disabling Chrome flag. On this machine on 2026-09-26, all
three paths passed 3/3 runs. Medians were Brownie Basic 1006 ms, direct
Playwright 950 ms, and agent-browser 892 ms. Differences this small on a local
page should not be treated as a general speed ranking. Agent-browser's
scripted CLI path does not provide Brownie's task schema, origin guard, or
structured mismatch result.

A separate Browser Use 0.13.10 run on the same localhost copy fixture used
Gemini 3.1 Flash Lite, completed in 8.5 seconds from agent run start, and
independently verified the textbox value as "solar report". Its usage summary
reported two model invocations and 15,729 tokens. The package reported zero
cost because its pricing accounting did not price that model; this is not
evidence that inference was free. That single agent run used a different setup
and timing boundary, so it is a capability and token-use check, not a
speed-ratio estimate.
