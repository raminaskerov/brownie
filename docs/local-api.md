# Brownie local API

The control room exposes the same typed run controls to programs on this computer.
It binds only to `127.0.0.1`, accepts one run at a time, and requires a fresh
random token in the `X-Brownie-Token` header. The token is written to
`artifacts/api-token` under the control room's runtime directory with owner-only
file permissions and removed on normal shutdown. Treat the token, results, and
private traces as local secrets.

Start the server from this checkout:

```bash
uv run brownie-ui --no-open
```

For a source run, the default runtime directory is the current working directory.
The server prints its URL and token-file path. The portable app uses its private
app-data directory. `--runtime-dir PATH` and `--port PORT` set explicit values.

A basic task can be started and polled with standard HTTP requests:

```bash
BROWNIE_API_TOKEN_VALUE=$(cat artifacts/api-token)
curl -sS -H "X-Brownie-Token: $BROWNIE_API_TOKEN_VALUE" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"basic","browser":"playwright","task_path":"tasks/report.json","inputs":["query=solar report"],"keep_open":false}' \
  http://127.0.0.1:8766/api/run
curl -sS -H "X-Brownie-Token: $BROWNIE_API_TOKEN_VALUE" \
  http://127.0.0.1:8766/api/state
```

`GET /api/state` returns status, activity flags, pending planner question,
structured `result`, `run_id`, `last_archive`, brief user-facing reply, event
summaries, and process logs.
Poll until `active` is false; inspect `result.status` and `result.stop_reason`,
not only the process status. A research run may report `can_reply: true` and a
`question` while active. Then `POST /api/reply` with `{"answer":"..."}` to
continue the same research state. Other authenticated endpoints are
`POST /api/stop`, `POST /api/close`, and `POST /api/quit` with `{}` bodies.
The control room UI uses these same endpoints.

`POST /api/run` accepts only the control room's typed fields: `mode` (basic,
research, search, predict, step, read, observe), `browser` (managed, playwright,
firefox, webkit, attach), `steerer` (jev or llm), `goal`, `url`, `task_path`,
`inputs`, `max_steps`, `max_pages`, `max_sources`, and `keep_open`. Fields that do
not apply to the chosen mode are ignored by command construction. This is a
local control API, not a remote browser service or an arbitrary command runner.
Browser actions still pass through Brownie's existing observation, validation,
and execution boundary.

## Run memory

After a control-room process finishes, Brownie stores the exact JSONL trace and
a compact JSON index under `artifacts/runs/<run_id>.jsonl` and
`artifacts/runs/<run_id>.json`. The index contains the goal, mode, process and
result status, last page, and planner proposals identified as proposals. It is
not fed back into future model calls or treated as verified knowledge. Files are
private, ignored by Git, and retained until you remove them. A run interrupted
by a process crash before cleanup may have only `last-run.jsonl`.

`GET /api/runs` lists up to 50 recent compact indexes. The control room can
open any listed exact trace at `/archive/<run_id>?t=<token>`. These endpoints
stay on localhost and require the same private token. The archive viewer
renders recorded events; it does not rerun the browser or planner.

Use `GET /api/memory` to list user-accepted decisions. `POST /api/memory`
accepts `{"decision":"...","source_run_id":"..."}`; the run ID is optional
but must name an existing archive when supplied. `POST /api/memory/remove`
accepts `{"id":"..."}`. The control room exposes the same actions. The ledger
is stored privately at `artifacts/accepted-decisions.json`, with at most 30
decisions of 500 characters each. Research planning reads a snapshot at run
start. Those decisions are prior user context and cannot count as cited
source evidence. No model output is promoted automatically.
