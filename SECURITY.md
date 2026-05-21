# Security Policy

## Security model

agent-fleet bridges LLM agents to real physical devices. The threat surface is real — treat these services accordingly.

**Network isolation via Tailscale**

All MCP bridge servers bind to `0.0.0.0` on their assigned port (Windows `:8766`, macOS `:8767`, Android `:8768`, iOS `:8769`) and rely on Tailscale for network-layer access control. Tailscale's WireGuard-based mesh ensures only authenticated, authorized nodes on your tailnet can reach these ports.

**Critical: do NOT expose MCP ports to the public internet.** If you run the bridges without Tailscale (LAN mode), restrict access at the OS firewall level. The setup wizard configures Windows Firewall rules and macOS pf/Application Firewall rules scoped to the Tailscale interface. Verify these rules are active before relying on them.

**Android ADB authorization**

The `android-device` bridge uses ADB (Android Debug Bridge). ADB authorization is stored in the device's trusted-key store (`~/.android/adbkey`). Anyone with access to the machine running the bridge — or to the ADB key pair — can send arbitrary ADB commands to the connected device. Keep the machine running the bridge physically and network-secure.

For Wireless Debugging mode (Android 11+), the ADB pairing PIN is short-lived but the resulting authorized key persists. Revoke unused ADB authorizations in the device's Developer Options.

**Principle of least privilege**

The MCP server processes run as a regular user (not root/SYSTEM). macOS setup requests only the TCC permissions the server actually needs (Accessibility, Screen Recording, Automation, optionally Full Disk Access). Windows setup registers a Scheduled Task that runs as the current user.

## Supported versions

This project is currently in **alpha**. Only the **latest alpha release** receives security fixes; older alpha versions are not patched.

| Version | Supported |
|---|---|
| Latest alpha | ✅ Yes |
| Older alpha tags | ❌ No — update to latest |
| v1.0+ (not yet released) | ✅ Will be supported per semver |

## Reporting a vulnerability

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Use GitHub's private vulnerability reporting instead:

1. Go to the [Security tab](https://github.com/metahub-tech/agent-fleet/security) of this repository.
2. Click **"Report a vulnerability"**.
3. Fill in the form describing the issue, steps to reproduce, and potential impact.

A maintainer will acknowledge the report within **5 business days** and work with you on a fix and coordinated disclosure timeline.
