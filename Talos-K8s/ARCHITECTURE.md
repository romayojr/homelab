# Talos Kubernetes architecture overview

Verified against the live cluster on 2026-11-15. Facts here come from
`kubectl`, `helm get values`, `talosctl`, and the Proxmox API, not from memory.

## 1. The short version

Talos Linux v1.12.0 with Kubernetes v1.35.0, five QEMU VMs on Proxmox
node proxmox-node04, all on local-lvm root disks, plus one Omni management VM
on CephPool. Flannel carries pod traffic, MetalLB hands out LAN load balancer
IPs from 10.0.0.100 to 10.0.0.200, Traefik v3.7.4 is the in-cluster ingress,
and TrueNAS NFS serves persistent volumes through csi-driver-nfs. Stateful
outside the cluster: Omni for Talos management and a NetBird server plus
reverse proxy on a Vultr VPS, which is how the `*.romeobag.ai` hostnames reach
cluster services from anywhere.

## 2. Hypervisor layer (Proxmox)

All Talos VMs sit on proxmox-node04 since the 2026-11-14 redeployment. Every
node is q35 machine, OVMF bios, cpu=host, balloon=0, virtio net with PVE
firewall on, qemu-guest-agent enabled, onboot=1 with a deliberate startup
order, ciuser romeo, nameserver 10.0.0.6 (Pi-hole) plus 1.1.1.1 and 8.8.8.8.

1. VM 701 Talos-CP-01, 2 cores, 4 GiB, 20G local-lvm, static 10.0.0.71,
   startup order 2.
2. VM 702 Talos-CP-02, 2 cores, 4 GiB, 20G local-lvm, static 10.0.0.72,
   startup order 3.
3. VM 703 Talos-CP-03, 2 cores, 4 GiB, 20G local-lvm, static 10.0.0.73,
   startup order 4.
4. VM 704 Talos-Worker-01, 4 cores, 8 GiB, 40G local-lvm, static 10.0.0.74,
   startup order 5.
5. VM 705 Talos-Worker-02, 4 cores, 8 GiB, 40G local-lvm, static 10.0.0.75,
   startup order 6.
6. VM 706 Omni, 4 cores, 6 GiB, 20G CephPool, static 10.0.0.70
   (ipconfig0 is static now, no DHCP pinning left to do), startup order 1 so
   it boots before the cluster.

Sizing rule on a 32-48 GiB host: RAM is the binding constraint, not disk.
etcd WAL and container images always live on local-lvm, never NFS. The
node04 local pool is a SATA M.2 (PM871b), so etcd fsync numbers are fine but
not NVMe-grade.

## 3. Node OS and control plane

1. Talos v1.12.0 on all five nodes (talosctl client 1.12.2 warns about the
   version skew, harmless).
2. Kubernetes v1.35.0, containerd 2.1.6, kernel 6.18.1-talos.
3. Cluster name `talos-proxmox-cluster`, API endpoint 10.0.0.71-73:6443.
4. Pod CIDR is per-node /24s from Flannel (for example 10.244.7.0/24 on CP-01).
5. Machine configs are managed through Omni on VM 706 (imported cluster,
   currently locked; see docs/omni-integration.md). Admin talosconfig is
   kept on admin machines, cert valid to 2027-01-11. Renew with
   `talosctl certificates renew`.
6. The 2026-11-14 event was a storage redeployment (disks restored onto
   local-lvm on node04), not a fresh bootstrap. Node age 304 days and etcd
   continuity prove the cluster identity never changed. Details in
   `docs/redeploy-runbook.md`.

## 4. Ingress and egress paths into the cluster

Two paths reach the same services.

```
LAN path:   client -> MetalLB IP 10.0.0.110 (web 30168 / websecure 30484
            NodePorts) -> in-cluster Traefik v3.7.4 -> services

NetBird path (internet / remote, used for *.romeobag.ai):
  wildcard *.romeobag.ai -> VPS 23.94.59.10 :443
    -> outer Traefik v3.6 (docker labels; serves netbird.romeobagay.net
       dashboard + gRPC; everything else falls to the tcp router
       HostSNI(*), priority 1, passthrough)
    -> netbird-proxy container :8443 over PROXY protocol v2 (pp-v2@file
       serversTransport from Netbird/traefik-dynamic.yaml)
    -> NetBird issues the browser-facing cert per service (certs volume
       netbird_proxy_certs; browser trust = NetBird internal CA)
    -> service access control gate (401 "NetBird Service" PIN page)
    -> overlay network route for 10.0.0.0/24 advertised by the
       netbird-agent Deployment inside the cluster
    -> upstream per service, for it-tools-k8s that is
       10.0.0.71:31622 (it-tools NodePort), service block in
       Netbird/traefik-dynamic.yaml
```

In-cluster networking objects:

1. MetalLB 0.15.3, pool `cluster-pool` 10.0.0.100-10.0.0.200, L2 advertisement
   `l2-adv`, frr disabled.
2. Traefik Helm release 40.3.0 (app v3.7.4), service type LoadBalancer with
   loadBalancerIP 10.0.0.110, 3 replicas, providers kubernetesIngress plus
   kubernetesCRD with class `traefik-external` watching namespaces traefik and
   default, dashboard enabled with basic-auth middleware,
   `--serversTransport.insecureSkipverify=true`, log level DEBUG.
3. In-cluster TLS secrets `romeobag-ai-tls` and `local-romeobag-ai-tls` in the
   default namespace, issued via cert-manager (DNS-01, recursive resolvers
   1.1.1.1 and 9.9.9.9).
4. NetBird agent runs as a 3-replica Deployment in namespace `netbird-agent`,
   hostNetwork + hostPID + privileged. On Talos workers that is mandatory for
   the raw socket / TC forwarding, and /dev/net is hostPath mounted. Manifests
   in `config/k8s/netbird-agent/`.

## 5. Storage

1. Root disks on local-lvm (see layer 2). No NFS for etcd or images, ever.
2. TrueNAS SCALE (10.0.0.3) zpool STILLMatic, dataset Talos-K8s (500 GiB),
   child dataset Talos-K8s/pvs exported for in-cluster PVs. The child dataset
   keeps PVE structural dirs (dump/import/snippets on the parent NFS mount)
   out of the PV tree.
3. csi-driver-nfs 4.13.6 (kubernetes-csi chart repo). StorageClass
   `nfs-retain`, parameters server 10.0.0.3, share
   /mnt/STILLMatic/Talos-K8s/pvs, reclaimPolicy Retain, Immediate binding,
   volume expansion allowed, PV name prefix `talos-`. Values file in
   `config/helm/csi-driver-nfs-values.yaml`.
4. Chart 4.x note the hard way: `archiveOnDelete` is no longer a StorageClass
   parameter, and StorageClass parameters are immutable, so a wrong SC needs
   delete plus reinstall, not a Helm upgrade.

## 6. Helm add-on inventory (as verified 2026-11-15)

1. cert-manager v1.20.2, namespace cert-manager, 3 replicas,
   values in `config/helm/cert-manager-values.yaml`.
2. metallb 0.15.3, namespace metallb-system, frr disabled.
3. traefik chart 40.3.0 / v3.7.4, namespace traefik, LB 10.0.0.110.
4. csi-driver-nfs 4.13.6, namespace kube-system, reinstalled 2026-11-14
   during the redeploy.

## 7. Workload inventory (namespaces and what actually runs)

1. default. it-tools (3/3, ghcr.io/sharevb/it-tools, NodePort 80:31622 ->
   targetPort 8080), nginx-production (3/3 with IngressRoutes for public
   hosts), nginx-staging (leftover Service with no backend, cleanup noted).
2. homepage. homepage Deployment exists but is 0/3 ready because its
   ServiceAccount is missing (FailedCreate). Drift, fix tracked in the
   incident doc follow-ups.
3. traefik. the ingress LB.
4. metallb-system. controller plus speakers.
5. cert-manager. issuer/webhook/cainjector.
6. netbird-agent. the overlay agent that lets the VPS proxy dial into LAN IPs.
7. kube-system. coredns, flannel, kube-proxy, csi-nfs-controller/node.

## 8. DNS and IP map (the parts that matter)

1. 10.0.0.70 Omni, .71-.73 CPs, .74-.75 workers, gw 10.0.0.1.
2. 10.0.0.110 Traefik LB, 10.0.0.100 web-demo-lb, pool up to 10.0.0.200.
3. DNS 10.0.0.6 (Pi-hole) answers `*.local.romeobagay.com` and LAN names.
4. Wildcard `*.romeobag.ai` points at the VPS 23.94.59.10 for the NetBird
   proxy path.
5. netbird.romeobagay.net is the NetBird dashboard/management on the same VPS,
   fronted by the outer Traefik with Let's Encrypt certs.

## 9. Backups (Proxmox vzdump, verified in the job list)

1. Job backup-7541d722-8643, 01:00, storage TN-PBS, keeps 7 daily, 4 weekly,
   3 monthly, includes 701-706 alongside the other VMs.
2. Job backup-9c1ab559-f6aa, 03:00, node04 local job to TN-VMs, keep-last 1,
   covers 985 plus 701-706.
3. PBS datastore path layout on this box is `/mnt/truenas/PBS/vm/<vmid>/...`
   (no backup/ dir) and PVE's content proxy can lie with `[]`. The redeploy
   runbook has the full restore-from-PBS story.

## 10. Secrets and config custody

1. Talos machine configs and admin certs. Omni DB (VM 706) plus talosconfig
   on admin machines and the password manager. Never committed.
2. NetBird server auth secret and sqlite encryption key. Live in
   `Netbird/config.yaml` on the VPS. That file is also sitting committed in
   this repo with real values, rotation is a follow-up in the incident doc.
3. NetBird proxy token. `Netbird/proxy.env` on the VPS.
4. NetBird agent setup key. Dashboard-issued, placeholder in the manifests
   here, real value never in git.
5. Cluster TLS (romeobag.ai, local.romeobagay.com). cert-manager Issuers plus
   the tls Secrets in-cluster.
6. Traefik dashboard basic-auth. Secret `traefik-dashboard-basic-auth` in
   namespace traefik.

## 11. Known drift as of 2026-11-15

1. Live it-tools image tag is `nightly`; the repo manifest pins 2026.1.4.
   The pin is the intended state.
2. homepage Deployment 0/3 (missing ServiceAccount homepage/homepage).
3. nginx-staging Service has no endpoints (backend Deployment gone).
4. netbirdio/netbird agent image is `latest`, pin it on the next touch.
5. NodePort 31622 answers plain HTTP on the LAN while the VPS service block
   dials it with the https scheme. See the verification note in the incident
   doc before trusting that URL blindly.
