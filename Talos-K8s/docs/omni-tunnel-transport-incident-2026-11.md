# Omni tunnel transport incident (2026-11-15): all links down, cluster stuck not-ready

## Symptom

Omni dashboard held `talos-proxmox-cluster` at not-ready. `omnictl get
clusterstatus` showed `connected: 0`, `kubernetesapiready: false`,
`controlplaneready: false`. `get machines` and `get links`: all 5 false. The
TALOS CA rotation (run after the import unlock, per omni-integration.md) had
stalled mid-rollout because config pushes ride the same transport.

Timeline: link resources last updated `2026-11-15T22:27:29Z` (~14:27 PST);
cluster recovered 17:00 PST same day.

## What was NOT broken (ruled out by probe)

- All six VMs (701-706) `running` on proxmox-node04, 19.6h uptime, no reboots.
- talosd on the LAN: TCP `10.0.0.71-75:50000` all open.
- K8s control plane: `https://10.0.0.7x:6443/healthz` answered 401 on all 3
  (server alive, anonymous rejected).
- Omni itself LAN-side: `10.0.0.70:443/8090/8095` open; `openssl s_client
  -connect 10.0.0.70:8090 -servername omni-gw.romeobag.ai` -> valid LE cert,
  `Verify return code: 0`.
- Node DNS target: `omni-gw.romeobag.ai` -> 23.94.59.10 (VPS), correct.

## Smoking gun

`openssl s_client -connect 23.94.59.10:8090 -servername omni-gw.romeobag.ai`
hangs with zero bytes returned. Raw TCP to `23.94.59.10:8090` connects (the
published listener is up) but nothing forwards behind it: the VPS relay hop
(netbird-proxy / tcprelay sidecar -> overlay -> 10.0.0.70:8090) was dead.
Every node stalls at TLS handshake, so all 5 links drop at once.

## Fix applied (cluster-side, no VPS work)

Pi-hole01 (10.0.0.6, drogon) Local DNS record:

```
10.0.0.70  omni-gw.romeobag.ai
```

added via the web UI (`/admin/settings/dnsrecords`, quick-add; verify under
Settings the FTL config applies it within ~60s, `dig @10.0.0.6` lags the UI).
Nodes re-dial DNS dynamically, so the LAN pin re-routes all five tunnels
through `10.0.0.70:8090` directly, where the machine API already serves the
exact `omni-gw.romeobag.ai` certificate. No node, Talos, or Omni config
touched. Precedent: `10.0.0.110 traefik.local.romeobag.ai` follows the same
pattern.

## Verification

- ~1 min after the DNS answer flipped: `get machines` 5/5 `CONNECTED true`,
  sustained across three polls.
- `get clusterstatus`: `ready: true`, `connected: 5`,
  `kubernetesapiready: true`, `controlplaneready: true`, no
  `tainted-by-importing` label.
- Stalled CA-rotation config resumed rolling on its own (machine resources
  bumped generation 7 -> 8).
- `ready: true` confirmed on the Omni dashboard.

## Client-tool aftermath (housekeeping done same day)

- `omnictl` must be v1.9.3 (server version); CLI at
  `~/.local/bin/omnictl-1.9.3`. Working default context `pubfix` in
  `~/.talos/omni/config` (url `https://omni.romeobag.ai`, siderov1 identity,
  PGP key reused from the registered `pub193` key file; the cluster-context
  key generated during rotation was never server-registered).
- Control host `/etc/hosts` pin `10.0.0.70 omni.romeobag.ai` keeps strict TLS
  working LAN-side; 8095/tcp must stay open on the Omni VM for kubeconfig.
- `kubectl` against the Omni kubeconfig needs the kubelogin plugin: installed
  v1.36.4 as `~/bin/kubectl-oidc-login` (also symlinked `kubectl-oidc_login`).
  Login chain is kubelogin -> dex (omni) -> authentik SSO with TOTP, so
  `kubectl oidc-login get-token ... --skip-open-browser` plus a manual click
  is the headless path.
- Stale contexts removed: talosctl `-1` duplicate and old direct-IP
  `talos-proxmox-cluster` context (CA-rotation invalidates its client certs);
  kubeconfig `admin@talos-proxmox-cluster`; omnictl `default-1`, `reuse`,
  `strict193`, `lan`.

## Open items left standing

1. The VPS `:8090` relay hop is still dead (out of scope that day). Only the
   nodes use `omni-gw`, and Pi-hole01 is their resolver (query log proves
   `talos-worker-01`), so the cluster is unaffected. Off-LAN dialing of
   `omni-gw` (remote talosctl through Omni) stays broken until the overlay
   router hop is repaired (see the router-peer login-expiry pattern).
2. `SiderolinkAPIConfigs` still advertises
   `wireguardadvertisedendpoint: 50.106.22.181:50180`, which matches nothing
   deployed. Harmless while `enforcegrpctunnel: true`, but correct it next
   time the config is touched.
3. Secondary resolver `10.0.0.99` still returns the public answer for
   `omni-gw`. Nodes do not use it; mirror the pin there if that changes.
