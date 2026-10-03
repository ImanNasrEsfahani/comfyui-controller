#!/usr/bin/env python3
"""Patch exactly four existing comfyui-controller files; never touch .env or Salad.

--check: validate expected upstream anchors, leave files unchanged.
--apply: validate all changes before writing anything.
The companion GitHub Action runs this script, tests, then commits to main.
"""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(content, original, replacement, filename):
    occurrences = content.count(original)
    if occurrences != 1:
        raise ValueError(f"{filename}: expected exactly one upstream anchor; found {occurrences}")
    return content.replace(original, replacement, 1)


def patch_control(src):
    name = 'backend/app/salad_control.py'
    if 'def set_keep_warm(enabled):' in src:
        return src
    src = replace_once(
        src,
        '        "autoscaler_enabled": bool(group.get("queue_autoscaler")),\n',
        '        "autoscaler_enabled": bool(group.get("queue_autoscaler")),\n'
        '        "keep_warm": (group.get("queue_autoscaler") or {}).get("min_replicas") == 1,\n'
        '        "min_replicas": (group.get("queue_autoscaler") or {}).get("min_replicas"),\n'
        '        "max_replicas": (group.get("queue_autoscaler") or {}).get("max_replicas"),\n',
        name,
    )
    src = replace_once(
        src,
        '    if (group.get("current_state") or {}).get("status") == "stopped":\n'
        '        return {"accepted": False, "message": "Already stopped"}\n',
        '    if int((group.get("queue_autoscaler") or {}).get("min_replicas", 0)) == 1:\n'
        '        raise ValueError("Keep Warm is enabled. Return to Auto first, then Stop.")\n'
        '    if (group.get("current_state") or {}).get("status") == "stopped":\n'
        '        return {"accepted": False, "message": "Already stopped"}\n',
        name,
    )
    src += '''\n\ndef set_keep_warm(enabled):
    """Change ONLY the autoscaler's 0/1 minimum; never change image or resources.

    PATCH may be asynchronous. Do not request additional replicas until a
    subsequent status() confirms pending_change=False. Changing configuration
    can reallocate instances; it cannot guarantee retaining physical hardware.
    """
    group = request("GET")
    if group.get("pending_change"):
        raise ValueError("A Salad configuration change is pending; refresh and retry")
    config = group.get("queue_autoscaler")
    if not isinstance(config, dict):
        raise ValueError("This group has no queue autoscaler; refusing to change it")
    if int(config.get("max_replicas", -1)) != 1:
        raise ValueError("Expected a single-GPU group (max_replicas=1)")
    current = int(config.get("min_replicas", -1))
    if current not in (0, 1):
        raise ValueError("Unexpected autoscaler minimum; refusing to overwrite it")
    target = 1 if enabled else 0
    if enabled and (group.get("current_state") or {}).get("status") == "stopped":
        raise ValueError("Start the Container Group first, then enable Keep Warm")
    if current == target:
        return {"accepted": False, "message": "Keep Warm is already " + ("ON" if enabled else "OFF")}

    allowed = (
        "desired_queue_length", "max_downscale_per_minute", "max_replicas",
        "max_upscale_per_minute", "min_replicas", "polling_period",
    )
    updated = {key: config[key] for key in allowed if key in config}
    updated["min_replicas"] = target
    request("PATCH", json_body={"queue_autoscaler": updated})
    if enabled:
        message = ("Keep Warm requested (minimum 1 GPU). Wait until pending change "
                   "clears; if there is no instance, press Start 1 GPU replica. "
                   "GPU billing continues while idle.")
    else:
        message = ("Auto scale-to-zero requested (minimum 0 GPUs). "
                   "Salad may take time to drain the queue and scale down. "
                   "Check instances before assuming billing has stopped.")
    return {"accepted": True, "message": message}
'''
    return src


def patch_main(src):
    name = 'backend/app/main.py'
    if '@app.post("/api/salad/keep-warm")' in src:
        return src
    anchor = '@app.post("/api/salad/stop")\n'
    replacement = '''@app.post("/api/salad/keep-warm")
def enable_keep_warm(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.set_keep_warm(True)
    except Exception as exc:
        raise salad_error(exc)


@app.post("/api/salad/auto-scale")
def enable_auto_scale(x_internal_token: str | None = Header(default=None)):
    check_admin_token(x_internal_token)
    try:
        return salad_control.set_keep_warm(False)
    except Exception as exc:
        raise salad_error(exc)


''' + anchor
    return replace_once(src, anchor, replacement, name)


def patch_frontend(src):
    name = 'frontend/src/App.jsx'
    if 'className="warm-controls"' in src:
        return src
    src = replace_once(
        src,
        '      replica: "Request one billable GPU replica now?"\n',
        '      replica: "Request one billable GPU replica now?",\n'
        '      "keep-warm": "Keep one billable RTX 5090 available even when the queue is empty? " +\n'
        '        "This may cause a Salad configuration update/reallocation. Enable before starting a job.",\n'
        '      "auto-scale": "Return to automatic scale-to-zero? Salad will release the GPU once idle; " +\n'
        '        "verify the instance count before assuming billing has stopped."\n',
        name,
    )
    src = replace_once(
        src,
        '              <span>Autoscaler: {instanceInfo.autoscaler_enabled ? "enabled" : "off"}</span>\n',
        '              <span>Autoscaler: {instanceInfo.autoscaler_enabled ? "enabled" : "off"}</span>\n'
        '              <span>Mode: <strong>{instanceInfo.keep_warm ? "Keep Warm · 1 GPU" : "Auto · scale to zero"}</strong></span>\n',
        name,
    )
    src = replace_once(
        src,
        '                  <button className="danger ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change}\n'
        '                    onClick={() => groupAction("stop")}>Stop worker</button>',
        '                  <button className="danger ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change || instanceInfo.keep_warm}\n'
        '                    title={instanceInfo.keep_warm ? "Return to Auto before stopping the GPU" : "Stop the whole Container Group"}\n'
        '                    onClick={() => groupAction("stop")}>Stop worker</button>',
        name,
    )
    src = replace_once(
        src,
        '                    <button className="danger ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change}\n'
        '                      onClick={() => groupAction("stop")}>Stop requested worker</button>',
        '                    <button className="danger ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change || instanceInfo.keep_warm}\n'
        '                      onClick={() => groupAction("stop")}>Stop requested worker</button>',
        name,
    )
    anchor = '            </div>\n          </>\n        ) : !instanceError && <p className="muted">Loading Salad instance status…</p>}\n'
    replacement = '''            </div>
            <div className="warm-controls">
              <div>
                <strong>{instanceInfo.keep_warm ? "Keep Warm is ON" : "Auto scale-to-zero is ON"}</strong>
                <p className="hint">
                  {instanceInfo.keep_warm
                    ? "Salad keeps a minimum of 1 billable GPU while this mode is enabled. Return to Auto when editing is finished."
                    : "Enable Keep Warm BEFORE a batch of edits so the GPU is not released between jobs."}
                </p>
                {instanceInfo.pending_change && <p className="hint">Salad is applying the change. Refresh to confirm before starting another action.</p>}
              </div>
              {instanceInfo.keep_warm ? (
                <button className="ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change}
                  onClick={() => groupAction("auto-scale")}>Return to Auto</button>
              ) : (
                <button className="ghost" disabled={groupBusy || !adminToken || !adminConfigured || instanceInfo.pending_change || instanceInfo.status === "stopped"}
                  onClick={() => groupAction("keep-warm")}>Keep Warm · 1 GPU</button>
              )}
            </div>
          </>
        ) : !instanceError && <p className="muted">Loading Salad instance status…</p>}
'''
    return replace_once(src, anchor, replacement, name)


def patch_styles(src):
    if '.warm-controls {' in src:
        return src
    return src + '''\n/* One-GPU editing session controls. */
.warm-controls { display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 14px; border: 1px solid #3b485d; border-radius: 12px;
  padding: 14px; margin-top: 14px; background: #111a27; }
.warm-controls > div { flex: 1 1 250px; }
.warm-controls strong { color: #dce9ff; }
.warm-controls .hint { margin: 6px 0 0; font-size: 12px; }
.warm-controls button { margin: 0; white-space: nowrap; }
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Verify patch anchors without writing files')
    mode.add_argument('--apply', action='store_true', help='Apply validated changes to all four files')
    args = parser.parse_args()
    jobs = {
        'backend/app/salad_control.py': patch_control,
        'backend/app/main.py': patch_main,
        'frontend/src/App.jsx': patch_frontend,
        'frontend/src/enhancements.css': patch_styles,
    }
    changes = {}
    for name, transform in jobs.items():
        file = ROOT / name
        before = file.read_text(encoding='utf-8')
        after = transform(before)
        changes[file] = (before, after)
        print(('CHANGE ' if before != after else 'UNCHANGED ') + name)
    if args.apply:
        for file, (before, after) in changes.items():
            if before != after:
                file.write_text(after, encoding='utf-8')
        print('Patch applied. No .env, Container Group or Salad resources changed.')
    else:
        print('Validation passed. No files were changed.')


if __name__ == '__main__':
    main()
