# Codex MCP Configuration

Run the MCP on the VM host so serial, HMP, debugger, and tracing paths remain
out-of-band from guest networking. A representative stdio entry is:

```toml
[mcp_servers.old_sun_box]
command = "uv"
args = ["--directory", "/path/to/im-an-old-sun-box--mcp", "run", "old-sun-mcp"]
env = { OLD_SUN_MCP_CONFIG = "/path/to/old-sun-mcp.toml" }
```

If Codex runs on another Mac, place a narrow authenticated relay between Codex
and this stdio process. Do not tunnel through the Solaris guest network: that
network is part of the system under test. The relay must preserve exact tool
schemas and evidence envelopes and must not broaden filesystem or shell access.
