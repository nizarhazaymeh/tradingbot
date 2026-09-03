#!/usr/bin/env python3
"""Start supervise.sh in its own session, so nothing upstream can take it down.

launchd on this machine will not start the agent from RunAtLoad and did not
revive it after a kill, despite KeepAlive — verified 3 Sep: runs=0 on load, and
`state = not running` 30s after a kill -9. `nohup ... & disown` was not enough
either: the supervisor stayed in the caller's process group and died with it.

os.setsid() puts the child in a brand-new session with no controlling terminal,
which is what actually survives the parent going away.
"""
import os, sys, subprocess
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs", "watchdog.log")

running = subprocess.run(["pgrep", "-f", "supervise.sh"],
                         capture_output=True, text=True).stdout.split()
if running:
    print(f"supervisor already running: {' '.join(running)}")
    sys.exit(0)

env = dict(os.environ, ACCOUNT=os.environ.get("ACCOUNT", "comp"),
           INTERVAL=os.environ.get("INTERVAL", "300"))
with open(LOG, "ab", buffering=0) as log:
    p = subprocess.Popen(["/bin/bash", os.path.join(ROOT, "scripts", "supervise.sh")],
                         cwd=ROOT, env=env, stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=True)
print(f"supervisor started detached: pid {p.pid}")
