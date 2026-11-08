#!/usr/bin/env python3
"""Portable, read-only board over the managed engine records.

No state is authored here. Regenerate after an engine mutation. Native pane
activation, provider trials, and restore trials are separate observed boundaries.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True


def esc(value):
    return html.escape(str(value if value is not None else "—"), quote=True)


def rows(value):
    if isinstance(value, dict):
        return [dict(v, _record_key=k) for k, v in value.items() if isinstance(v, dict)]
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def ident(record):
    return str(record.get("task_id") or record.get("id") or record.get("path") or record.get("_record_key") or "unknown")


def anchor(value):
    return "task-" + hashlib.sha256(str(value).encode()).hexdigest()[:20]


def local_link(root, value, label=None):
    """Only root-contained local files become links, never source-supplied URLs."""
    if not isinstance(value, str) or not value or "://" in value:
        return esc(label if label is not None else value)
    base = Path(root).resolve()
    path = Path(value)
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        path.relative_to(base)
    except ValueError:
        return esc(label if label is not None else value)
    return '<a href="' + esc(path.as_uri()) + '">' + esc(label if label is not None else value) + "</a>"


def value(record, *keys, default="—"):
    for key in keys:
        if key in record and record[key] is not None:
            candidate = record[key]
            return json.dumps(candidate, ensure_ascii=False, sort_keys=True) if isinstance(candidate, (dict, list)) else candidate
    return default


def table(headers, body, caption):
    if not body:
        return '<p class="empty">No ' + esc(caption.lower()) + " records in this scope</p>"
    return '<div class="scroll"><table><caption>' + esc(caption) + "</caption><thead><tr>" + "".join("<th scope=\"col\">" + esc(h) + "</th>" for h in headers) + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + c + "</td>" for c in row) + "</tr>" for row in body) + "</tbody></table></div>"


def section(section_id, title, content):
    return '<section id="' + section_id + '"><h2>' + esc(title) + "</h2>" + content + "</section>"


def render_data(data, root, scope=".", error=None):
    """Render an engine snapshot without executing embedded commands or markup."""
    if isinstance(data, list):
        data = {"tasks": data}
    if not isinstance(data, dict):
        data, error = {}, error or "Engine returned an invalid board snapshot"
    tasks = rows(data.get("tasks", []))
    runs, messages, evidence = [], [], []
    for task in tasks:
        for key, destination in (("runs", runs), ("messages", messages), ("evidence", evidence)):
            for record in rows(task.get(key, [])):
                destination.append(dict(record, _task=ident(task), _task_path=task.get("path", "")))
    # Some adapters provide flattened records. Avoid rendering both copies.
    for key, destination in (("runs", runs), ("messages", messages), ("evidence", evidence)):
        if not destination:
            destination.extend(rows(data.get(key, [])))
    sources = rows(data.get("sources", []))
    health = data.get("health", {})
    health = health if isinstance(health, dict) else {"reported": health}
    needs = [t for t in tasks if t.get("needs_you") or t.get("blocker") or t.get("pending_decisions") or t.get("error")]
    body = '<a class="skip" href="#main">Skip to current work</a><header><h1>Agent system</h1><p>Read-only engine snapshot · scope ' + esc(scope) + '</p><p class="boundary">Files and engine records are authoritative · refresh this page after a change · native activation and live trials remain deferred</p></header>'
    nav = (("tasks", "Tasks"), ("needs-you", "Needs you"), ("runs", "Runs"), ("inbox", "Inbox"), ("evidence", "Evidence"), ("sources", "Sources"), ("health", "Health and recovery"), ("resources", "Resources"), ("adapters", "Adapters"))
    body += '<nav aria-label="Board views">' + "".join('<a href="#' + k + '">' + esc(t) + "</a>" for k, t in nav) + '</nav><main id="main">'
    if error:
        body += '<aside role="alert" class="error"><h2>Board could not load</h2><p>' + esc(error) + '</p><p>This page does not represent a successful fresh read · inspect engine records and regenerate</p></aside>'
    table_rows, details = [], []
    for task in tasks:
        task_id = ident(task)
        revision = value(task, "requirement_rev", "revision")
        path = task.get("path", "")
        current = task.get("contract", task)
        current = current if isinstance(current, dict) else task
        table_rows.append([
            '<a href="#' + anchor(task_id) + '">' + esc(value(task, "title", "name", "task_id", "id")) + "</a>",
            esc(value(task, "goal", "outcome")), esc(value(task, "owner")), esc(value(task, "state", "status")),
            esc(revision), esc(value(task, "next")), esc(value(task, "updated_at", "updated", "freshness")),
            esc(value(task, "needs_you", "blocker", default="none reported")),
        ])
        packet = str(Path(path) / "0 start.md") if path else ""
        details.append('<details id="' + anchor(task_id) + '"><summary>' + esc(task_id) + ' · requirement revision ' + esc(revision) + '</summary><dl><dt>Current packet</dt><dd>' + local_link(root, packet) + '</dd><dt>Canonical contract</dt><dd>' + local_link(root, str(Path(path) / "systems/task.json") if path else "") + '</dd><dt>Allowed paths</dt><dd>' + esc(value(current, "allowed_paths", "write_paths")) + '</dd><dt>Acceptance</dt><dd>' + esc(value(current, "acceptance", "criteria", "acceptance_ids")) + '</dd><dt>Corrections</dt><dd>' + esc(value(task, "corrections", "latest_correction")) + '</dd><dt>Lease health</dt><dd>' + esc(value(task, "lease_health")) + '</dd><dt>Queued messages</dt><dd>' + esc(value(task, "queued_messages", default="not observed")) + '</dd><dt>Load error</dt><dd>' + esc(value(task, "error", default="none reported")) + '</dd></dl></details>')
    body += section("tasks", "Current tasks", table(["Task", "Outcome", "Owner", "State", "Revision", "Next", "Updated", "Needs you"], table_rows, "Tasks") + "".join(details))
    body += section("needs-you", "Needs you", table(["Task", "Decision or blocker", "Current revision"], [[esc(ident(t)), esc(value(t, "pending_decisions", "blocker", "error", "needs_you")), esc(value(t, "requirement_rev", "revision"))] for t in needs], "Needs-you"))
    run_rows = []
    for run in runs:
        receipt = run.get("boot_receipt") or run.get("receipt") or {}
        receipt = receipt if isinstance(receipt, dict) else {"reported": receipt}
        loaded = value(run, "acknowledged_rev", default=value(receipt, "requirement_rev", "revision", "reported", default="no load receipt"))
        run_rows.append([esc(value(run, "run_id", "id")), esc(value(run, "task_id", "_task")), esc(value(run, "harness", "adapter")), esc(value(run, "actor", "owner")), esc(value(run, "state", "status")), esc(value(run, "requirement_rev", "revision")), esc(loaded), esc(value(run, "lease", "lease_until", "expires_at")), esc(value(run, "artifact", "submission"))])
    body += section("runs", "Runs and ownership", table(["Run", "Task", "Harness", "Actor", "State", "Run revision", "Loaded revision", "Lease", "Artifact"], run_rows, "Runs"))
    message_rows = []
    for message in messages:
        message_rows.append([esc(value(message, "message_id", "id")), esc(value(message, "task_id", "_task", "to")), esc(value(message, "type", "kind")), esc(value(message, "requirement_rev", "revision")), esc(value(message, "state", "status", default="queued")), esc(value(message, "delivered", "delivered_at", "delivery", default="no delivery receipt")), esc(value(message, "acknowledged", "acknowledged_at", "ack", default="no acknowledgement")), esc(value(message, "text", "body", "content"))])
    body += section("inbox", "Inbox delivery and acknowledgement", '<p>Queued messages are separate from delivery and acknowledgement · a message is never authorization</p>' + table(["Message", "Task", "Type", "Revision", "Queue state", "Delivery", "Acknowledgement", "Body"], message_rows, "Inbox"))
    evidence_rows = []
    for record in evidence:
        evidence_rows.append([esc(value(record, "evidence_id", "report_id", "id")), esc(value(record, "task_id", "_task")), esc(value(record, "criterion", "criterion_id", "acceptance_id")), esc(value(record, "requirement_rev", "revision")), esc(value(record, "stale", "freshness", default="not assessed")), esc(value(record, "observed", "result", "outcome", "passed")), local_link(root, record.get("path") or record.get("artifact_path") or "", value(record, "path", "artifact_path", "artifact", default="no linked artifact")), esc(value(record, "challenge", "finding", "gap"))])
    body += section("evidence", "Acceptance evidence", table(["Report", "Task", "Criterion", "Revision", "Stale", "Observed result", "Proof", "Challenge or gap"], evidence_rows, "Evidence"))
    source_rows = []
    for record in sources:
        locations = rows(record.get("locations", []))
        originals = '<br>'.join(local_link(root, location.get("path", "")) + (' (unavailable)' if location.get('available') is False else '') for location in locations) if locations else local_link(root, record.get("path") or record.get("original") or "", value(record, "path", "original"))
        extraction = record.get("extraction") if isinstance(record.get("extraction"), dict) else {}
        source_rows.append([esc(value(record, "source_id", "id")), esc(value(record, "sha256", "hash")), originals, esc(value(record, "ocr_status", "ocr", default=value(extraction, "status"))), esc(value(record, "significance", "selected_significance", "meaning")), esc(value(record, "linked_tasks", "decisions", "links"))])
    body += section("sources", "Original inputs and selected significance", table(["Source", "Hash", "Original", "OCR", "Significance", "Linked work"], source_rows, "Sources"))
    recovery = rows(data.get("recovery", data.get("operations", [])))
    health_rows = [[esc(k), esc(json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v)] for k, v in sorted(health.items())]
    health_rows.extend([esc(ident(task)), esc(value(task, "lease_health", "health", "error", default="not observed"))] for task in tasks)
    body += section("health", "Health and recovery", table(["Signal", "Observed value"], health_rows, "Health") + '<p>Missing health observations mean unverified · a heartbeat does not prove a loaded revision or completed work</p>' + table(["Operation", "State", "Recovery"], [[esc(value(r, "operation_id", "id")), esc(value(r, "phase", "state", "status")), esc(value(r, "conflicts", "recovery", "instruction", "error"))] for r in recovery], "Recovery"))
    resources = rows(data.get("resources", []))
    body += section("resources", "Resources and retained work", table(["Resource", "Owner", "Task", "State", "Unfinished work", "Recovery pointer"], [[esc(value(r, "id", "resource_id")), esc(value(r, "owner")), esc(value(r, "task_id")), esc(value(r, "status", "state")), esc(value(r, "unfinished", "references")), local_link(root, r.get("recovery"), value(r, "recovery"))] for r in resources], "Resources") + '<p>Retirement does not delete a resource · unfinished references remain visible</p>')
    adapters = rows(data.get("adapters", []))
    dispatches = rows(data.get("dispatches", []))
    body += section("adapters", "Adapter capabilities and dispatch receipts", table(["Adapter", "Capability", "Evidence status", "Boundary"], [[esc(value(a, "id", "adapter", "name")), esc(value(a, "capabilities", "capability")), esc(value(a, "evidence", "status", "observed")), esc(value(a, "boundary", "unsupported", "notes"))] for a in adapters], "Adapters") + table(["Dispatch", "Task", "State", "Boundary or receipt"], [[esc(value(d, "id", "dispatch_id")), esc(value(d, "task_id")), esc(value(d, "status", "state")), esc(value(d, "boundary", "receipt", "error"))] for d in dispatches], "Dispatches"))
    body += '</main><footer>Generated from the same managed engine used by ctx · this page launches no sessions and performs no mutations</footer>'
    style = 'body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f8fafc;color:#172033}header,main,footer,nav{max-width:1400px;margin:auto;padding:1rem}h1,h2{line-height:1.2}nav{display:flex;gap:1rem;flex-wrap:wrap;position:sticky;top:0;background:#eef2ff;z-index:1}a{color:#1d4ed8}a:focus-visible,summary:focus-visible{outline:3px solid #d97706;outline-offset:3px}section{scroll-margin-top:6rem;margin:2rem 0}.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;background:white}caption{text-align:left;font-weight:600;padding:.5rem}th,td{padding:.65rem;text-align:left;vertical-align:top;border:1px solid #cbd5e1;overflow-wrap:anywhere}th{background:#eff6ff}details{border:1px solid #cbd5e1;background:white;padding:1rem;margin:.5rem 0}summary{cursor:pointer}dt{font-weight:600}dd{margin:0 0 1rem;overflow-wrap:anywhere}.error{border:2px solid #b91c1c;background:#fff1f2;padding:1rem}.empty,.boundary{color:#475569}.skip{position:absolute;left:-9999px}.skip:focus{left:1rem;top:1rem;background:white;padding:1rem;z-index:2}@media(max-width:600px){body{font-size:15px}nav{position:static}header,main,footer,nav{padding:.75rem}th,td{padding:.4rem}}'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'"><title>Agent system board</title><style>' + style + '</style></head><body>' + body + '</body></html>'


def render(root, output, scope="."):
    """Write an escaped static snapshot atomically, returning observed load status."""
    error, data = None, {}
    try:
        from agent_core import Store
        store = Store(root, commit=False)
        from agent_services import view_records
        with store.locked():
            data = store.board(scope=scope)
            if isinstance(data, list):
                data = {"tasks": data}
            if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
                raise ValueError("engine board did not return task records")
            service = view_records(store, scope=scope)
            if not isinstance(service, dict):
                raise ValueError("service views did not return records")
            # Service-derived views cannot overwrite the canonical task snapshot.
            data.update({k: v for k, v in service.items() if k != "tasks"})
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp = tempfile.mkstemp(prefix=".board-", suffix=".html", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(render_data(data, root, scope, error))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return {"path": str(target), "scope": scope, "ok": error is None, "error": error}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("CTX_ROOT") or str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--scope", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = render(args.root, args.output, args.scope)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
