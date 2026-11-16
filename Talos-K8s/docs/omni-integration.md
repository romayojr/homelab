# Omni integration runbook (live since 2026-11-15)

Verified against the running cluster and Omni on 2026-11-15. Every value here
was observed live, not carried over from the design docs.

## What is running

- Omni **v1.9.3** (`ghcr.io/siderolabs/omni:v1.9.3`) in container `omni` on
  VM 706, compose at `/home/romeo/omni/compose.yaml`.
- Talos cluster `talos-proxmox-cluster` (CP 10.0.0.71-73, workers .74-.75) is
  **imported** into Omni and stays **locked**. All 5 `Machine` and `Link`
  resources report `CONNECTED true`, and they survived the post-import
  reconfigure reboots.
- Import backups on the admin host: `~/.talos/omni-import-backups/`
  (`...-2026-11-15.zip`, `-reimport.zip`, `-final.zip`, `-gw4.zip`).
- VM 706 safety net: Proxmox snapshot `pre-eventsink-2026-11-15`, plus
  `compose.yaml.bak-eventsink` and `compose.yaml.bak-mapi` next to the compose.

## Two hostnames, two jobs

| Hostname | Job | Path |
|---|---|---|
| `omni.romeobag.ai` | human dashboard + SSO (Authentik) | NetBird proxy HTTPS service -> `10.0.0.70:443` |
| `omni-gw.romeobag.ai` | nodes, CLI, machine API | machine API advertised on `:8090` (see below) |

Never point the machine path at `omni.romeobag.ai`; the proxy maps exactly one
backend per hostname and the dashboard owns that name.

## Machine transport (the part that took the debugging)

Omni flags on VM 706 (kebab-case only; dotted config-path flags crash-loop the
container):

```
--machine-api-advertised-url=https://omni-gw.romeobag.ai:8090
--machine-api-cert=/etc/omni/tls/fullchain.pem
--machine-api-key=/etc/omni/tls/priv.key
--siderolink-use-grpc-tunnel
```

The cert is the `*.romeobag.ai` Let's Encrypt wildcard, so nodes validate it
without pins. `enforcegrpctunnel: true` shows up on
`SiderolinkAPIConfigs.omni.sidero.dev`, and node dmesg confirms tunnels
(`siderolink connection configured`, peer endpoints `:50889`).

`omni-gw.romeobag.ai` resolves through the public wildcard to the VPS
`23.94.59.10`. Two relays carry node traffic from the VPS into the NetBird
overlay toward `10.0.0.70`:

1. The NetBird proxy service for `omni-gw.romeobag.ai` (HTTPS mode with
   *Skip TLS verification* on, resource destination `10.0.0.70:8090`).
2. `omni-relay` in `~/netbird/docker-compose.yml` on the VPS: a `docker:cli`
   sidecar that keeps a statically-linked TCP relay (source:
   `Talos-K8s/tools/tcprelay.c`, build `gcc -O2 -static`) alive inside the
   `netbird-proxy` container, listening on `:8090` and forwarding raw bytes to
   `10.0.0.70:8090` over the overlay. The VPS compose also publishes
   `8090:8090/tcp` on the proxy container (backup:
   `docker-compose.yml.bak-8090`).

Relay 2 is self-healing: the sidecar re-injects the binary and restarts it
every 30s if the proxy container is recreated.

Split-horizon note, updated same day: a Pi-hole A record pinning
`omni-gw.romeobag.ai -> 10.0.0.70` (Pi-hole01, 10.0.0.6) is live and is the
recovery path when the VPS relay hop dies - see
`docs/omni-tunnel-transport-incident-2026-11.md`. The public wildcard still
answers off-LAN; the pin only changes LAN resolvers, and the Talos nodes use
Pi-hole01 (visible in its query log). The old removed pin was on the
dashboard hostname `omni.romeobag.ai`, which remains public-only.
`omni.local -> 10.0.0.70` still exists in Pi-hole but is not used by node
config.

## CLI pairing (version trap)

The server is v1.9.3. A current `omnictl` fails with
`unknown service cosi.resource.State`. Pair it with **omnictl v1.9.3**
(`https://github.com/siderolabs/omni/releases/download/v1.9.3/omnictl-linux-amd64`).

Working context (LAN direct, cert is for the wildcard name so the IP needs the
skip flag):

```
omnictl config add pub193 --url https://10.0.0.70 --identity romayojr@gmail.com
omnictl --context pub193 --insecure-skip-tls-verify get machines
```

Auth is a browser public-key approval (PGP key under `~/.talos/keys/`), not a
password.

Strict-TLS default context (no skip flag) as of 2026-11-15 evening:

```
# ~/.talos/omni/config -> context: pubfix
# url: https://omni.romeobag.ai  (control host /etc/hosts pins it to 10.0.0.70)
omnictl get machines
```

`pubfix` reuses the registered `pub193` PGP key file, copied to
`pubfix-<identity>.pgp` under `~/.talos/keys/`. Do not run auth-bearing
omnictl calls blindly: a failed or killed attempt regenerates the context key
in place and silently unregisters it.

`kubectl` against the Omni kubeconfig (`omni-on-prem-talos-proxmox-cluster`
context) needs kubelogin: `~/bin/kubectl-oidc-login` (v1.36.4, plus
`kubectl-oidc_login` symlink). Headless path:
`kubectl oidc-login get-token <same args as kubeconfig exec>
--skip-open-browser --authentication-timeout-sec 900`, then click the printed
URL in a browser that already has the Omni/authentik session (TOTP applies).

talosctl through the Omni proxy authenticates with its OWN key file
(`~/.talos/keys/<talosconfig-context>-<identity>.pgp`), which must be
server-registered once via the printed `/authenticate?flow=cli` browser
approval (same one-click mechanism as omnictl). Node addressing via the
proxy: machine UUID, IP, or hostname without the `.local` suffix all
resolve; `talos-cp-01.local` does not.

## Import facts (for a future re-import)

```
omnictl --context pub193 --insecure-skip-tls-verify cluster import \
  --dry-run \
  --talosconfig ~/.talos/config --talos-context talos-proxmox-cluster \
  --nodes 10.0.0.71,10.0.0.72,10.0.0.73,10.0.0.74,10.0.0.75 \
  --talos-version v1.12.0 --kubernetes-version v1.35.0
```

- Dry run renders the full plan (schematic
  `ce4c9805...` validated without `--force`); drop `--dry-run` and add
  `-O <backup.zip> --wait-timeout 10m` for live.
- Import creates secrets, cluster, 2 machine sets, 5 machine set nodes, 5
  config patches, then marks the cluster **locked**.
- Purge-then-reimport is the clean repair for a half-populated import:
  `cluster unlock <name>` then `cluster delete <name>
  --destroy-disconnected-machines`.
- Keep the cluster locked until `get machines` shows all 5 `CONNECTED true`;
  unlocking early allows Omni edits against an empty machine inventory.
  Unlock at all only when you want Omni (not talosconfig) to own machine
  config going forward.

## Health checks that actually mean something

```
omnictl --context pub193 --insecure-skip-tls-verify get machines   # 5x true
omnictl get machines                     # pubfix default, strict TLS, same answer
omnictl get links                        # 5x true
kubectl --context omni-on-prem-talos-proxmox-cluster get nodes     # 5x Ready (kubelogin)
talosctl -c talos-proxmox-cluster -n 10.0.0.71 health --wait-timeout 90s
```

`talosctl -n <worker> health` fails with etcd `no request forwarding` - that
is CLI semantics (workers run no etcd), not cluster damage. Trust
`kubectl get nodes` for workers. Via the Omni proxy, `health` service checks
(kubelet, boot sequence, diagnostics, memory, disk) all pass, but the final
`waiting for all k8s nodes to report` sub-check returns
`PermissionDenied: not authorized` - the proxy maps CLI auth read-restricted
for that sub-call; cosmetic, not a cluster fault. Also note Talos 1.12 has no
`platformid`/`clustername` resources anymore; use `get machines` or `health`
to prove proxy auth works.

## Known open item

0. (NEW 2026-11-15 evening) The VPS-side omni-gw relay hop (`23.94.59.10:8090`
   -> overlay -> `10.0.0.70:8090`) is dead: TCP accepts, zero bytes forwarded.
   The Pi-hole `omni-gw` LAN pin keeps the five node tunnels working around it
   (see `omni-tunnel-transport-incident-2026-11.md`), but off-LAN dialing of
   `omni-gw` stays broken until the overlay router hop is repaired. Also still
   stale in `SiderolinkAPIConfigs`: `wireguardadvertisedendpoint:
   50.106.22.181:50180` matches nothing deployed (harmless while
   `enforcegrpctunnel: true`).

The in-cluster `netbird-agent` deployment (namespace `netbird-agent`) has one
pod crash-looping: its client authenticates with an SSO device flow that can
never complete headless. Pre-existing, unrelated to Omni (nodes reach Omni
over the WAN, not through those pods). Fix when touched: swap to a setup key.
