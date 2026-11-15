# Talos-K8s

This folder is the home base for my Talos Kubernetes cluster: the architecture,
the November 2026 redeployment, the NetBird certificate incident and fix, and the
config files that keep it all running. Verified against the live cluster on
2026-11-15.

What this cluster is. Three control planes plus two workers running Talos Linux
v1.12.0 and Kubernetes v1.35.0 as QEMU VMs (701 to 705) on proxmox-node04, with
an Omni management server on VM 706. In-cluster apps: it-tools, nginx-production,
Traefik ingress, MetalLB, cert-manager, a NetBird agent, and TrueNAS NFS storage.

What lives where:

1. `ARCHITECTURE.md` in this folder. The full architectural overview of the
   current deployment, from the Proxmox VM layer up to the HTTPS access paths.
2. `docs/redeploy-runbook.md`. How the 2026-11-14 redeployment went down, in the
   order it actually worked, plus the verification checklist and the traps.
3. `docs/netbird-cert-incident-2026-11.md`. The NetBird Certificate Issuer
   failure, the Traefik `it-tools-k8s` fix, the PIN auth hardening in front of
   the service, and the verification evidence.
4. `config/helm/`. The four Helm values files exactly as applied
   (`helm get values` exports, secrets-free).
5. `config/k8s/netbird-agent/`. The in-cluster NetBird agent manifests,
   sanitized. The setup key is a placeholder on purpose.
6. `config/talos/`. How to regenerate machine configs and where the real ones
   actually live. Machine configs and admin certs never go in git.

Related folders that already existed and stay canonical:

1. `Kubernetes/projects/` keeps the app manifests (it-tools, metalLB, nginx).
   The it-tools service is now a NodePort on 31622 because that is the endpoint
   the NetBird reverse proxy on the VPS dials into the cluster.
2. `Netbird/` keeps the VPS side of the stack (compose, server config, the
   Traefik dynamic file). The `it-tools-k8s` service block added on 2026-11-15
   is committed there.

How I administer it from an admin machine:

1. talosconfig at `~/.talos/config`, context `talos-proxmox-cluster`,
   admin cert expires 2027-01-11.
2. kubeconfig at `~/.kube/config`, context `admin@talos-proxmox-cluster`.
3. Omni v1.9.3 on VM 706: dashboard https://omni.romeobag.ai (SSO), nodes and
   machine API via https://omni-gw.romeobag.ai:8090. Cluster is imported and
   locked. Full runbook: docs/omni-integration.md.
