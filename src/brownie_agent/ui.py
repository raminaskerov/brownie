# ruff: noqa: E501
"""Small localhost control surface for Brownie's existing CLI runner."""

import argparse
import json
import os
import secrets
import signal
import subprocess
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .config import default_ui_runtime_dir
from .launcher import worker_command
from .settings import provider_status, save_provider_keys, validate_provider_settings

MAX_BODY_BYTES = 64 * 1024
MAX_LOG_LINES = 160
MAX_REPLY_CHARS = 24_000
MODES = {"search", "predict", "step", "read", "observe"}
BROWSERS = {"managed", "playwright", "attach"}
STEERERS = {"jev", "llm"}


def _bounded_int(value: Any, name: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return result


def build_command(config: dict, *, trace_path: Path) -> list[str]:
    """Translate typed UI fields to CLI arguments without accepting free-form flags."""
    mode = str(config.get("mode", "search"))
    browser = str(config.get("browser", "managed"))
    steerer = str(config.get("steerer", "jev"))
    goal = str(config.get("goal", "")).strip()
    url = str(config.get("url", "")).strip()
    if mode not in MODES:
        raise ValueError("Unknown task mode")
    if browser not in BROWSERS:
        raise ValueError("Unknown browser mode")
    if steerer not in STEERERS:
        raise ValueError("Unknown steerer")
    if mode == "search" and browser == "attach":
        raise ValueError("Search cannot take ownership of an existing attached Chrome session")
    if mode in {"search", "predict", "step"} and not goal:
        raise ValueError("This task needs a goal")
    if mode != "search" and not url:
        raise ValueError("This task needs a start URL")
    if url and not url.startswith(("http://", "https://", "file://")):
        raise ValueError("Start URL must begin with http://, https://, or file://")

    max_steps = _bounded_int(config.get("max_steps", 8), "Action limit", minimum=1, maximum=100)
    max_pages = _bounded_int(config.get("max_pages", 3), "Page limit", minimum=1, maximum=30)
    command = worker_command()
    if browser == "managed":
        command.append("--managed-cdp")
    elif browser == "playwright":
        command.append("--headed")
    else:
        command.extend(("--attach", "--use-open-tab"))

    if mode == "search":
        command.extend((
            "--search", "--goal", goal, "--steerer", steerer,
            "--max-steps", str(max_steps), "--max-pages", str(max_pages),
        ))
    elif mode in {"predict", "step"}:
        command.extend((f"--{mode}", "--goal", goal, "--steerer", steerer, url))
    elif mode == "read":
        command.extend(("--read-page", url))
    else:
        command.append(url)
    if bool(config.get("keep_open", True)) and browser != "attach" and mode != "predict":
        command.append("--keep-open")
    command.extend(("--trace", str(trace_path), "--json"))
    return command


def _read_trace(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                events.append(item)
    except OSError:
        return []
    return events


def _event_summary(item: dict) -> str | None:
    event, data = item.get("event"), item.get("data", {})
    if event == "steering_result":
        choice = data.get("choice", {})
        target = f" -> {choice.get('target_name')}" if choice.get("target_name") else ""
        confidence = choice.get("confidence")
        score = f" - confidence {confidence:.3f}" if isinstance(confidence, (int, float)) else ""
        return f"Chose {choice.get('operation', 'unknown')}{target}{score}"
    if event == "execution_result":
        result = data.get("result", {})
        return f"{result.get('operation', 'Action')}: {result.get('status', 'unknown')}"
    if event == "page_read_view":
        viewport = data.get("observation", {}).get("viewport", {})
        return f"Read viewport at scroll position {viewport.get('scroll_y', 0)}"
    if event == "run_result":
        return "Run finished"
    if event == "error":
        return f"Error: {data.get('message', 'unknown error')}"
    return None


def _clip(text: str) -> str:
    if len(text) <= MAX_REPLY_CHARS:
        return text
    return text[:MAX_REPLY_CHARS] + "\n\n[Shortened here; the inspector keeps the complete result.]"


def _result_reply(result: Any) -> str:
    if not isinstance(result, dict):
        return "Brownie finished, but its result was not structured as expected."
    if "source" in result:
        source = result.get("source")
        if source:
            return _clip(
                f"I found and read: {source.get('title', 'Untitled')}\n"
                f"{source.get('url', '')}\n\n{source.get('material', '')}"
            )
        page = result.get("last_page", {})
        return (
            f"I stopped: {result.get('stop_reason', 'unknown reason')}\n"
            f"Last page: {page.get('title', 'Untitled')}\n{page.get('url', '')}"
        )
    prediction = result.get("prediction")
    if isinstance(prediction, dict):
        target = f" -> {prediction.get('target_name')}" if prediction.get("target_name") else ""
        execution = result.get("execution")
        ending = f"\nExecution: {execution.get('status')}" if isinstance(execution, dict) else "\nNothing was executed."
        return f"I chose {prediction.get('operation', 'unknown')}{target}.{ending}"
    if "combined_text" in result:
        return _clip(
            f"I read {result.get('title', 'the page')} ({result.get('url', '')}).\n\n"
            f"{result.get('combined_text', '')}"
        )
    if "title" in result and "url" in result:
        return (
            f"I observed: {result.get('title', 'Untitled')}\n{result.get('url', '')}\n\n"
            f"Visible text: {len(result.get('text', ''))} characters\n"
            f"Interactive elements: {len(result.get('elements', []))}"
        )
    return _clip(json.dumps(result, indent=2, ensure_ascii=False))


class RunManager:
    """Own one Brownie subprocess and expose its narrow lifecycle to the UI."""

    def __init__(self, runtime_dir: Path):
        self.runtime_dir = runtime_dir.resolve()
        self.trace_path = self.runtime_dir / "artifacts" / "last-run.jsonl"
        self.inspector_path = self.trace_path.with_suffix(".html")
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._status = "idle"
        self._message = "Ready"
        self._logs: list[str] = []
        self._stop_requested = False

    def _append_log(self, source: str, line: str) -> None:
        clean = line.rstrip()
        if not clean:
            return
        with self._lock:
            self._logs.append(f"{source}: {clean}")
            self._logs = self._logs[-MAX_LOG_LINES:]
            if "Brownie finished. Press Enter to close its browser." in clean:
                self._status = "awaiting_close"
                self._message = "Finished - browser left open for you"

    def start(self, config: dict) -> None:
        validate_provider_settings(self.runtime_dir, config)
        command = build_command(config, trace_path=self.trace_path)
        environment = os.environ.copy()
        environment["BROWNIE_RUNTIME_DIR"] = str(self.runtime_dir)
        environment["PYTHONUNBUFFERED"] = "1"
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("A Brownie run is already active")
            self.trace_path.parent.mkdir(parents=True, exist_ok=True)
            self._logs = [f"command: {json.dumps(command, ensure_ascii=False)}"]
            self._status, self._message, self._stop_requested = "starting", "Starting Brownie and Chrome...", False
            options: dict[str, Any] = {
                "cwd": self.runtime_dir, "stdin": subprocess.PIPE, "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE, "text": True, "bufsize": 1, "env": environment,
            }
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                options["start_new_session"] = True
            self._process = subprocess.Popen(command, **options)
            process = self._process
            self._status, self._message = "running", "Brownie is working"
        threading.Thread(target=self._read_stream, args=(process.stdout, "output"), daemon=True).start()
        threading.Thread(target=self._read_stream, args=(process.stderr, "status"), daemon=True).start()
        threading.Thread(target=self._wait, args=(process,), daemon=True).start()

    def _read_stream(self, stream, source: str) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            self._append_log(source, line)
        stream.close()

    def _wait(self, process: subprocess.Popen[str]) -> None:
        code = process.wait()
        with self._lock:
            if process is not self._process:
                return
            if self._stop_requested:
                self._status, self._message = "stopped", "Stopped by you"
            elif code == 0:
                self._status, self._message = "completed", "Finished"
            else:
                self._status, self._message = "failed", f"Brownie exited with status {code}"

    def close_browser(self) -> None:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise RuntimeError("There is no open Brownie browser")
            if self._status != "awaiting_close":
                raise RuntimeError("Brownie has not finished yet")
            if process.stdin is None:
                raise RuntimeError("The browser control channel is unavailable")
            process.stdin.write("\n")
            process.stdin.flush()
            self._status, self._message = "closing", "Closing Brownie's browser..."

    def stop(self) -> None:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                raise RuntimeError("There is no active run")
            self._stop_requested = True
            self._status, self._message = "stopping", "Stopping after the current browser call..."
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGINT)

    def save_settings(self, payload: dict) -> dict[str, bool]:
        return save_provider_keys(self.runtime_dir, payload)

    def ensure_idle(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise RuntimeError("Stop or close the active Brownie run before quitting")

    def snapshot(self) -> dict:
        events = _read_trace(self.trace_path)
        summaries = [summary for item in events if (summary := _event_summary(item)) is not None]
        result = None
        for item in reversed(events):
            if item.get("event") == "run_result":
                result = item.get("data", {}).get("result")
                break
        with self._lock:
            return {
                "status": self._status, "message": self._message,
                "active": self._process is not None and self._process.poll() is None,
                "can_close": self._status == "awaiting_close",
                "can_stop": self._status in {"starting", "running"},
                "event_count": len(events), "events": summaries[-30:],
                "reply": _result_reply(result) if result is not None else "",
                "logs": list(self._logs), "inspector_ready": self.inspector_path.exists(),
                "settings": provider_status(self.runtime_dir),
            }


HTML = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brownie control room</title>
<style>
:root{--paper:#f1efe8;--ink:#1e211f;--muted:#68706b;--line:#d4d0c5;--panel:#fbfaf6;--green:#315d47;--red:#a33b32}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 system-ui,sans-serif}header{align-items:center;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;padding:18px 28px}h1{font-size:22px;margin:0}h2{font-size:16px;margin:0 0 14px}.status{background:#e2e7e1;border-radius:99px;color:var(--green);font-weight:700;padding:7px 12px}main{display:grid;gap:18px;grid-template-columns:minmax(300px,390px) minmax(420px,1fr);margin:0 auto;max-width:1500px;padding:20px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px}label{color:var(--muted);display:block;font-size:12px;font-weight:700;letter-spacing:.04em;margin:13px 0 5px;text-transform:uppercase}input,select,textarea{background:white;border:1px solid #bbb6aa;border-radius:7px;color:var(--ink);font:inherit;padding:9px 10px;width:100%}textarea{min-height:112px;resize:vertical}.row{display:grid;gap:10px;grid-template-columns:1fr 1fr}.toggle{align-items:center;display:flex;gap:8px;margin:13px 0}.toggle input{width:auto}button{background:var(--green);border:0;border-radius:7px;color:white;cursor:pointer;font:inherit;font-weight:700;padding:10px 14px}button.secondary{background:#dedbd1;color:var(--ink)}button.danger{background:var(--red)}button:disabled{cursor:not-allowed;opacity:.45}.buttons,.tabs{display:flex;flex-wrap:wrap;gap:8px;margin-top:15px}.help{color:var(--muted);font-size:13px}.work{display:grid;gap:18px;grid-template-rows:auto auto minmax(420px,1fr);min-width:0}.reply{background:#fff;border-left:4px solid var(--green);min-height:100px;padding:13px;white-space:pre-wrap;word-break:break-word}.timeline{color:var(--muted);margin:0;padding-left:22px}.timeline li{margin:5px 0}.tabs{margin:0 0 10px}.tabs button{background:#dedbd1;color:var(--ink)}.tabs button.active{background:var(--ink);color:white}iframe{background:white;border:1px solid var(--line);border-radius:7px;height:68vh;width:100%}pre{background:#171918;color:#e8e8e4;max-height:68vh;overflow:auto;padding:14px;white-space:pre-wrap;word-break:break-word}.hidden{display:none}.error{color:var(--red);min-height:22px}@media(max-width:850px){main{grid-template-columns:1fr}.row{grid-template-columns:1fr}}
details.settings{border-top:1px solid var(--line);margin-top:18px;padding-top:14px}details.settings summary{cursor:pointer;font-weight:700}.key-status{color:var(--muted);font-size:13px;margin:10px 0}
</style></head><body>
<header><h1>Brownie control room</h1><div class="status" id="status">Ready</div></header>
<main><section class="panel"><h2>Start Brownie</h2>
<label for="mode">Task</label><select id="mode"><option value="search">Search the web and read one source</option><option value="predict">Predict one move - execute nothing</option><option value="step">Execute one selected move</option><option value="read">Read successive page viewports</option><option value="observe">Observe one page</option></select>
<div id="goal-wrap"><label for="goal">Goal</label><textarea id="goal" placeholder="Find the official..."></textarea></div>
<div id="url-wrap" class="hidden"><label for="url">Start URL</label><input id="url" type="url" placeholder="https://example.com"></div>
<div class="row"><div><label for="browser">Browser start</label><select id="browser"><option value="managed">Ordinary Chrome + CDP</option><option value="playwright">Playwright-owned Chrome</option><option value="attach">Existing debug Chrome</option></select></div><div id="steerer-wrap"><label for="steerer">Steering</label><select id="steerer"><option value="jev">Jev</option><option value="llm">LLM</option></select></div></div>
<div class="row" id="budgets"><div><label for="max-steps">Actions</label><input id="max-steps" type="number" min="1" max="100" value="8"></div><div><label for="max-pages">Pages</label><input id="max-pages" type="number" min="1" max="30" value="3"></div></div>
<label class="toggle"><input id="keep-open" type="checkbox" checked> Leave Brownie's Chrome open after it finishes</label><p class="help" id="browser-help"></p>
<div class="error" id="error"></div><div class="buttons"><button id="start">Start run</button><button class="secondary" id="close" disabled>Close Brownie browser</button><button class="danger" id="stop" disabled>Stop run</button><button class="secondary" id="quit">Quit Brownie</button></div>
<details class="settings"><summary>Model keys</summary><p class="help">Saved only on this computer. Brownie never shows a saved key again.</p>
<label for="typesafe-key">TypeSafe key for Jev</label><input id="typesafe-key" type="password" autocomplete="off">
<label for="gemini-key">Gemini key for LLM and typing</label><input id="gemini-key" type="password" autocomplete="off">
<div class="key-status" id="key-status">Checking saved keys...</div><button class="secondary" id="save-settings">Save keys</button>
</details></section>
<div class="work"><section class="panel"><h2>Brownie says</h2><div class="reply" id="reply">No run yet.</div></section><section class="panel"><h2>What happened</h2><ol class="timeline" id="events"><li>Waiting for a run.</li></ol></section>
<section class="panel"><div class="tabs"><button id="inspector-tab" class="active">Inspector</button><button id="logs-tab">Process log</button><button id="refresh" class="secondary">Refresh inspector</button></div><iframe id="inspector" title="Last Brownie run inspector"></iframe><pre id="logs" class="hidden">No process output.</pre></section></div></main>
<script>
const TOKEN='__TOKEN__',$=id=>document.getElementById(id);let lastInspectorCount=-1,lastEvents='',lastLogs='';
function setText(id,value){if($(id).textContent!==value)$(id).textContent=value}
function formState(){return{mode:$('mode').value,goal:$('goal').value,url:$('url').value,browser:$('browser').value,steerer:$('steerer').value,keep_open:$('keep-open').checked,max_steps:Number($('max-steps').value),max_pages:Number($('max-pages').value)}}
function keyState(){return{typesafe_api_key:$('typesafe-key').value,gemini_api_key:$('gemini-key').value}}
async function updateSettings(){const response=await fetch('/api/state',{headers:{'X-Brownie-Token':TOKEN}}),state=await response.json(),settings=state.settings||{};setText('key-status','Jev: '+(settings.jev_configured?'ready':'key needed')+' · LLM: '+(settings.llm_configured?'ready':'key needed')+' · Typing: '+(settings.text_configured?'ready':'key needed'))}
async function post(path,body={}){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Brownie-Token':TOKEN},body:JSON.stringify(body)}),value=await response.json();if(!response.ok)throw new Error(value.error||'Request failed');return value}
function adaptForm(){const mode=$('mode').value,browser=$('browser').value;$('url-wrap').classList.toggle('hidden',mode==='search');$('goal-wrap').classList.toggle('hidden',!['search','predict','step'].includes(mode));$('steerer-wrap').classList.toggle('hidden',!['search','predict','step'].includes(mode));$('budgets').classList.toggle('hidden',mode!=='search');if(mode==='search'&&browser==='attach')$('browser').value='managed';$('browser').querySelector('[value="attach"]').disabled=mode==='search';$('keep-open').disabled=$('browser').value==='attach'||mode==='predict';const help={managed:'Uses a dedicated profile and starts ordinary headed Chrome through localhost CDP.',playwright:"Starts Playwright-owned headed Chrome with Brownie's isolated profile.",attach:'Reuses a matching tab in Chrome already started with remote debugging. Brownie does not close it.'};$('browser-help').textContent=help[$('browser').value]}
async function update(){try{const response=await fetch('/api/state',{headers:{'X-Brownie-Token':TOKEN}}),state=await response.json();setText('status',state.message);$('start').disabled=state.active;$('close').disabled=!state.can_close;$('stop').disabled=!state.can_stop;setText('reply',state.reply||(state.active?'Brownie is working...':'No result yet.'));const eventKey=JSON.stringify(state.events);if(eventKey!==lastEvents){$('events').replaceChildren(...(state.events.length?state.events:['Waiting for decisions.']).map(text=>{const li=document.createElement('li');li.textContent=text;return li}));lastEvents=eventKey}const logText=state.logs.join('\n')||'No process output.';if(logText!==lastLogs){$('logs').textContent=logText;lastLogs=logText}if(state.inspector_ready&&state.event_count!==lastInspectorCount&&['completed','failed','stopped','awaiting_close'].includes(state.status)){$('inspector').src='/inspector?t='+encodeURIComponent(TOKEN)+'&v='+state.event_count;lastInspectorCount=state.event_count}}catch(error){setText('error',error.message)}}
$('save-settings').addEventListener('click',async()=>{$('error').textContent='';try{await post('/api/settings',keyState());$('typesafe-key').value='';$('gemini-key').value='';await updateSettings()}catch(error){$('error').textContent=error.message}});updateSettings();
$('quit').addEventListener('click',async()=>{try{await post('/api/quit');document.body.innerHTML='<main><section class="panel"><h1>Brownie has stopped.</h1><p>You can close this tab.</p></section></main>'}catch(error){$('error').textContent=error.message}});
$('mode').addEventListener('change',adaptForm);$('browser').addEventListener('change',adaptForm);$('start').addEventListener('click',async()=>{$('error').textContent='';try{await post('/api/run',formState());await update()}catch(error){$('error').textContent=error.message}});$('close').addEventListener('click',async()=>{try{await post('/api/close')}catch(error){$('error').textContent=error.message}});$('stop').addEventListener('click',async()=>{try{await post('/api/stop')}catch(error){$('error').textContent=error.message}});$('refresh').addEventListener('click',()=>{$('inspector').src='/inspector?t='+encodeURIComponent(TOKEN)+'&v='+Date.now()});$('inspector-tab').addEventListener('click',()=>{$('inspector').classList.remove('hidden');$('logs').classList.add('hidden');$('inspector-tab').classList.add('active');$('logs-tab').classList.remove('active')});$('logs-tab').addEventListener('click',()=>{$('logs').classList.remove('hidden');$('inspector').classList.add('hidden');$('logs-tab').classList.add('active');$('inspector-tab').classList.remove('active')});adaptForm();update();setInterval(update,800);
</script></body></html>'''


class UIRequestHandler(BaseHTTPRequestHandler):
    server: "BrownieServer"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _headers(self, status: HTTPStatus, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-src 'self'")
        self.end_headers()

    def _json(self, value: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._headers(status, "application/json; charset=utf-8")
        self.wfile.write(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def _authorized(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Brownie-Token", ""), self.server.token)

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/":
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8")
            self.wfile.write(HTML.replace("__TOKEN__", self.server.token).encode("utf-8"))
        elif path == "/api/state":
            if not self._authorized():
                self._json({"error": "Unauthorized"}, HTTPStatus.FORBIDDEN)
            else:
                self._json(self.server.manager.snapshot())
        elif path == "/inspector":
            supplied = parse_qs(parsed.query).get("t", [""])[0]
            if not secrets.compare_digest(supplied, self.server.token):
                self._headers(HTTPStatus.FORBIDDEN, "text/plain; charset=utf-8")
                self.wfile.write(b"Unauthorized")
                return
            inspector = self.server.manager.inspector_path
            if not inspector.exists():
                self._headers(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                self.wfile.write(b"No inspector exists yet. Start a run first.")
                return
            try:
                body = inspector.read_bytes()
            except OSError:
                self._headers(HTTPStatus.SERVICE_UNAVAILABLE, "text/plain; charset=utf-8")
                self.wfile.write(b"The inspector is being refreshed. Try again.")
                return
            self._headers(HTTPStatus.OK, "text/html; charset=utf-8")
            self.wfile.write(body)
        else:
            self._headers(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
            self.wfile.write(b"Not found")

    def do_POST(self) -> None:
        if not self._authorized():
            self._json({"error": "Unauthorized"}, HTTPStatus.FORBIDDEN)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json({"error": "Invalid request size"}, HTTPStatus.BAD_REQUEST)
            return
        if size > MAX_BODY_BYTES:
            self._json({"error": "Request is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        try:
            payload = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("Request body must be an object")
            if self.path == "/api/run":
                self.server.manager.start(payload)
            elif self.path == "/api/settings":
                self.server.manager.save_settings(payload)
            elif self.path == "/api/close":
                self.server.manager.close_browser()
            elif self.path == "/api/quit":
                self.server.manager.ensure_idle()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif self.path == "/api/stop":
                self.server.manager.stop()
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
        except (RuntimeError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
            return
        self._json({"ok": True})


class BrownieServer(ThreadingHTTPServer):
    manager: RunManager
    token: str


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Start Brownie's private local control room.")
    result.add_argument("--port", type=int, default=8766, help="Local port (default: 8766)")
    result.add_argument("--no-open", action="store_true", help="Do not open the control page automatically")
    result.add_argument("--runtime-dir", type=Path, default=default_ui_runtime_dir(), help="Brownie runtime directory")
    return result


def main() -> None:
    args = parser().parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    args.runtime_dir.mkdir(parents=True, exist_ok=True)
    os.environ["BROWNIE_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    server = BrownieServer(("127.0.0.1", args.port), UIRequestHandler)
    server.manager, server.token = RunManager(args.runtime_dir), secrets.token_urlsafe(32)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Brownie control room: {url}")
    print("Only this computer can connect. Press Ctrl+C here to stop the control room.")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBrownie control room stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
