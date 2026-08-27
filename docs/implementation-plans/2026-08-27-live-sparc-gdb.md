# SUN-002 implementation plan

1. Extend strict configuration with run-specific console logs and named,
   loopback-only SPARC debugger profiles.
2. Add a bounded `gdb-multiarch` batch runner and structured capture parsing.
3. Connect `debugger.capture` to the exact run monitor and retain cleanup proof.
4. Add focused tests and update configuration and operations documentation.
5. Deploy a local TOML profile on `niagara-playbox` and run the live smoke test
   after the reboot produces a QEMU run.
