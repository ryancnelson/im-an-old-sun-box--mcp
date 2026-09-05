"""Deploy a tested wheel to the configured console pane; rollback on failed health."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time
from urllib.request import urlopen


def wait_healthy(revision, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:8877/healthz", timeout=2) as response:
                if json.load(response).get("revision") == revision:
                    return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("deployed revision failed its health check")


def activate(new_command, previous_command, restart, check):
    try:
        restart(new_command)
        check()
    except Exception:
        restart(previous_command)
        raise


def deploy(checkout, revision):
    runtime = Path.home() / ".local/state/old-sun-console"
    config = json.loads((runtime / "deployment.json").read_text())
    tmux = str(Path.home() / "bin/safe-tmux")
    pane = config["pane"]

    def tmux_value(format):
        # The user's wrapper prints its guardrail result before tmux's value.
        return subprocess.check_output((tmux, "display-message", "-p", "-t", pane, format), text=True).strip().splitlines()[-1]

    previous = tmux_value("#{pane_start_command}")
    command = shlex.join(("env", f"OLD_SUN_CONSOLE_REVISION={revision}",
                          str(checkout / ".venv/bin/python"), "-m", "old_sun_mcp.console_launcher",
                          "--hosts", str(checkout / "examples/console-hosts-minnie.json"),
                          "--runtime-dir", str(runtime), "--state", config["state"],
                          "--control-socket", config["control_socket"], "--port", "8877"))

    def restart(value):
        subprocess.run((tmux, "set-option", "-p", "-t", pane, "remain-on-exit", "on"), check=True)
        if tmux_value("#{pane_dead}") != "1":
            os.kill(int(tmux_value("#{pane_pid}")), signal.SIGTERM)
            deadline = time.monotonic() + 15
            while tmux_value("#{pane_dead}") != "1":
                if time.monotonic() >= deadline:
                    raise RuntimeError("console did not stop gracefully; refusing forced termination")
                time.sleep(0.25)
        subprocess.run((tmux, "respawn-pane", "-t", pane, "-c", config["working_directory"], value), check=True)

    activate(command, previous, restart, lambda: wait_healthy(revision))
    record = runtime / "deployment-result.json"
    record.write_text(json.dumps({"revision": revision, "checkout": str(checkout), "previous_command": previous}))
    record.chmod(0o600)
    print(f"DEPLOYED {revision} http://localhost:8877 (health verified)", flush=True)
