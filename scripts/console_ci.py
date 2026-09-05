"""Woodpecker host runner: exact-commit test, build, and loopback deployment."""
import fcntl
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ORIGIN = "https://github.com/ryancnelson/im-an-old-sun-box--mcp.git"


def validate_revision(value):
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("an exact 40-character commit SHA is required")
    return value


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main(revision, stage):
    revision = validate_revision(revision)
    if stage not in {"test", "build", "deploy"}:
        raise ValueError("unknown CI stage")
    target = (platform.system(), platform.machine())
    if target not in {("Linux", "x86_64"), ("Darwin", "arm64")}:
        raise ValueError(f"unsupported build target: {target}")
    root = Path.home() / ".cache/old-sun-console-ci"
    root.mkdir(parents=True, exist_ok=True)
    with (root / f"{revision}.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        checkout = root / revision
        if not (checkout / ".git").exists():
            run("git", "init", str(checkout))
            run("git", "remote", "add", "origin", ORIGIN, cwd=checkout)
            run("git", "fetch", "--depth=1", "origin", revision, cwd=checkout)
            run("git", "checkout", "--detach", "FETCH_HEAD", cwd=checkout)
        actual = subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=checkout, text=True).strip()
        if actual != revision:
            raise ValueError("checkout revision mismatch")
        run("git", "diff", "--exit-code", "HEAD", "--", cwd=checkout)
        tools = root / "tools"
        uv = tools / "bin/uv"
        with (root / "tools.lock").open("w") as tools_lock:
            fcntl.flock(tools_lock, fcntl.LOCK_EX)
            if not uv.exists():
                run(sys.executable, "-m", "venv", str(tools))
                run(str(tools / "bin/pip"), "install", "uv==0.9.22")
        python = checkout / ".venv/bin/python"
        if stage == "test":
            if not shutil.which("socat") or not shutil.which("node"):
                raise RuntimeError("CI requires socat and Node; do not skip relay/browser tests")
            run(str(uv), "sync", "--locked", "--extra", "test", "--python", sys.executable, cwd=checkout)
            run(str(python), "-m", "pytest", "-q", cwd=checkout)
            run("node", "--test", "tests/console_directory.test.cjs", cwd=checkout)
            (checkout / ".ci-tested").write_text(revision)
        elif stage == "build":
            if (checkout / ".ci-tested").read_text() != revision:
                raise RuntimeError("build requires tests for this exact revision")
            run(str(uv), "build", cwd=checkout)
            wheels = list((checkout / "dist").glob("*.whl"))
            if len(wheels) != 1:
                raise RuntimeError("expected exactly one wheel")
            # Test the installed wheel, not just the editable source checkout.
            run(str(uv), "pip", "install", "--python", str(python), "--no-deps", "--reinstall", str(wheels[0]), cwd=checkout)
            run(str(python), "-m", "pytest", "-q", cwd=checkout)
            (checkout / ".ci-built").write_text(revision)
        else:
            if target != ("Darwin", "arm64"):
                raise ValueError("console deployment runs only on Darwin arm64")
            if (checkout / ".ci-built").read_text() != revision:
                raise RuntimeError("deployment requires a built and tested wheel")
            head = subprocess.check_output(("git", "ls-remote", "origin", "refs/heads/main"), cwd=checkout, text=True).split()[0]
            if head != revision:
                raise ValueError("only the current main commit may deploy")
            sys.path.insert(0, str(checkout / "scripts"))
            from console_deploy import deploy
            deploy(checkout, revision)


if __name__ == "__main__":
    main(*sys.argv[1:])
