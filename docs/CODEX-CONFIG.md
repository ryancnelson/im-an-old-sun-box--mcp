# Codex MCP Configuration

Run the MCP on the VM host so serial, HMP/QMP, debugger, and tracing paths
remain out-of-band from guest networking.

## Codex CLI on the VM host

Install the wheel in a dedicated virtual environment, place the host-local TOML
at `~/.config/old-sun-mcp/config.toml`, and register the absolute executable:

```bash
python3 -m venv ~/.local/share/old-sun-mcp/venv
~/.local/share/old-sun-mcp/venv/bin/pip install \
  'im_an_old_sun_box_mcp-0.1.0-py3-none-any.whl[mcp]'
codex mcp add old_sun_box -- \
  ~/.local/share/old-sun-mcp/venv/bin/old-sun-mcp
```

Restart Codex after changing its MCP configuration. Confirm the registration
with `codex mcp get old_sun_box`, then begin with observational calls:

```text
Use the old_sun_box MCP only, without shell commands, to list live runs and
report QEMU status for the live run. Do not call disruptive tools.
```

If the profile enables `console.*`, the MCP process also needs the bearer token
named by `console.token_env`. Supply it from the host's secret manager. Do not
put the token in TOML or in the `codex mcp add` command line.

## Codex running from a project checkout

A development checkout can instead launch the server through `uv`:

```toml
[mcp_servers.old_sun_box]
command = "uv"
args = ["--directory", "/path/to/im-an-old-sun-box--mcp", "run", "--extra", "mcp", "old-sun-mcp"]
env = { OLD_SUN_MCP_CONFIG = "/path/to/old-sun-mcp.toml" }
```

## Codex on another machine

For a trusted lab, SSH can act as the narrow stdio transport while the MCP
process still runs beside QEMU:

```bash
codex mcp add old_sun_box -- ssh -T vm-host \
  /absolute/path/to/old-sun-mcp
```

Do not tunnel through the Solaris guest network: that network is part of the
system under test. Any relay must preserve exact tool schemas and evidence
envelopes and must not broaden filesystem or shell access.
