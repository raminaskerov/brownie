# Basic-mode task contracts

Basic mode executes a finite local JSON contract without calling Jev, Gemini, or another model. It is intended for understood, repetitive browser work where stopping on a mismatch is preferable to improvising.

The contract selects targets only from each fresh Brownie observation. It cannot contain selectors, XPath, JavaScript, coordinates, node IDs, or executable code.

## Run a task

    uv run brownie --basic-task tasks/report.json \
      --input query="solar report" \
      --headed

Use the JSON output and private trace when diagnosing a contract:

    uv run brownie --basic-task tasks/report.json \
      --input query="solar report" \
      --json --trace artifacts/basic-run.jsonl

Command-line inputs are visible to the local process list, and an opt-in trace can contain typed values. Do not use this interface for passwords, tokens, payment data, or other secrets.

## Contract format

    {
      "version": 1,
      "name": "Find the official solar report",
      "start_url": "https://search.example/",
      "allowed_origins": [
        "https://search.example",
        "https://reports.example"
      ],
      "inputs": ["query"],
      "steps": [
        {
          "operation": "TYPE_TEXT",
          "target": {
            "role": "searchbox",
            "name": "Search"
          },
          "input": "query"
        },
        {
          "operation": "SUBMIT",
          "target": {
            "role": "searchbox",
            "name": "Search"
          }
        },
        {
          "operation": "CLICK",
          "target": {
            "role": "link",
            "name": "Official solar report",
            "context_contains": "Reports Institute",
            "destination_contains": "/annual-report"
          }
        },
        {
          "operation": "ASSERT",
          "check": {
            "title_contains": "Solar report"
          }
        },
        {
          "operation": "READ_PAGE",
          "max_scrolls": 3
        }
      ]
    }

The example domains are placeholders. A contract is site-specific evidence about a workflow, not a promise that the same names will exist on unrelated sites.

### Task fields

- **version:** currently must be 1.
- **name:** human-readable task name.
- **start_url:** page Brownie opens before the first step.
- **allowed_origins:** exact HTTP or HTTPS origins the task may visit. The start origin must be included. Local fixture contracts may use file://.
- **inputs:** declared input names. Every declared input must be supplied exactly once, and undeclared inputs are rejected.
- **steps:** one to fifty validated steps.

Unknown fields are rejected rather than ignored.

### Target matching

Targets require an exact role and accessible name after case and whitespace normalization. Optional context_contains and destination_contains fields disambiguate repeated links without becoming selectors.

The target must be unique in the fresh current viewport and must offer the requested operation. Brownie stops when the target is missing or ambiguous. If frames, open shadow roots, or observer limits make the page incomplete, a missing target is reported as perception_incomplete rather than target_not_found.

### Supported operations

- **TYPE_TEXT:** fills one observed editable target from either a declared input or a contract literal.
- **SUBMIT:** currently accepted only on an observed searchbox.
- **CLICK:** currently accepted only for an observed link with a destination, or a checkbox, radio, or switch. Link destinations are checked against allowed_origins before clicking.
- **SCROLL_DOWN / SCROLL_UP:** one viewport movement through the shared action boundary.
- **ASSERT:** checks one or more text_contains, title_contains, or url_contains conditions.
- **READ_PAGE:** bounded read-only page traversal. It must be the final step and becomes the task output.
- **DONE:** explicit successful stop. It must be the final step.

Generic buttons and non-search form submission are deliberately rejected because Brownie cannot yet distinguish a harmless continuation from a purchase, message, deletion, or other consequential action strongly enough for unattended replay.

## Stop behavior

Basic mode does not ask a model to repair a failed workflow. It returns a structured stop reason such as:

- target_not_found or target_ambiguous;
- perception_incomplete;
- unsupported_click or unsupported_submit;
- origin_not_allowed;
- auth_required or challenge;
- stale_observation_limit;
- operation_unavailable;
- assertion_failed;
- no_effect.

A stale observation causes Brownie to re-observe and rematch the contract target, but it never retries a mutation. All actual effects still pass through the same executor used by manual, Jev, LLM, and search modes.

## Current boundary

Basic mode is available through the CLI and the local control room. The UI
accepts a validated task path and explicit NAME=VALUE inputs; it does not expose
free-form command flags. A saved-task library, user confirmation for broader
button actions, downloads, dialogs, closed shadow roots, and frame-local
scrolling remain later milestones. Visible frame and open-shadow-root controls
now use the same semantic matching, freshness check, and validated executor as
top-document controls.
