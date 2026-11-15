# Talos redeployment runbook (2026-11-14)

This is what the node04 storage redeployment actually looked like, in the
order that worked, so the next one is a checklist instead of an archaeology
dig. The cluster itself was NOT re-bootstrapped. VM disks were restored onto
node04's local-lvm and the same etcd/cluster identity came back up on top of
them. Node age 304 days and an unbroken etcd history prove it.

## 1. Decision gates, in order

1. Credentials gate first. Without a working talosconfig you cannot judge
   anything else. Omni (VM 706) holds machine configs and admin certs for
   enrolled clusters, and a stale talosconfig on any admin machine stays valid
   for months, a roughly 300-day-old one re-authenticated this whole cluster.
   A version handshake warning is cosmetic. No certs and no Omni means
   rebuild with fresh certs, because a restored-but-unmanageable cluster is
   worse than a rebuild.
2. Backup inventory gate. Enumerate PBS archives on the datastore filesystem
   (`/mnt/truenas/PBS/vm/<vmid>/<stamp>/` on this build), not through PVE's
   content proxy which can answer `[]` even when archives exist. Talos
   families on disk, primary 2026-11-11T05:00Z, fallback 2026-11-09T11:0x.
   Restore one family only, and same-day manual backups prune each other under
   keep-last=1, so assume exactly one archive per VM survives.
3. Restore-vs-rebuild gate for the CPs. Restoring three CPs from the same
   backup run keeps etcd member IDs consistent. Mixed-family restores risk
   member-ID mismatch, and app manifests are in git anyway, so rebuild wins
   when families do not match.

## 2. What was done

1. Restored 701-705 (CP-01/02/03, Worker-01/02) to proxmox-node04 `local-lvm`
   and 706 (Omni) to CephPool. The Talos base template is VM 7000
   Talos-Cloud-Init on node04, `qm clone 7000 <name> --full --storage
   local-lvm` if a fresh node is ever needed.
2. IPs are static in the VM cloud-init (`ipconfig0`) and hard-bound into the
   Talos machine configs, so .71-.75 are not negotiable. Omni got a static
   .70 rather than a DHCP pin.
3. Boot order set by design, 706 (order=1) then 701 to 705 (order=2..6), all
   onboot=1. This build rejects `after=` and `up-delay=` in the startup
   property, bare `order=N` only. Bring CP-01 up first, confirm etcd has
   quorum (2/3 works), then the rest.
4. Re-added 701-706 to the vzdump jobs after restore, destroyed VMIDs silently
   drop out of jobs. Current state, verified in the job list: job
   backup-7541d722-8643 at 01:00 to TN-PBS keeps 7 daily 4 weekly 3 monthly
   (includes 701-706), and node04 job backup-9c1ab559-f6aa at 03:00 to TN-VMs
   keeps last 1.
5. Stateful storage rebuilt on TrueNAS. zpool STILLMatic, dataset Talos-K8s
   (500 GiB) is also mounted in PVE as NFS storage Talos-K8s, and the child
   dataset Talos-K8s/pvs is what csi-driver-nfs exports so PVE structural
   directories never mingle with PV folders.
6. Reinstalled csi-driver-nfs 4.13.6 and created StorageClass `nfs-retain`
   (Retain, Immediate, expansion on, server 10.0.0.3, share
   /mnt/STILLMatic/Talos-K8s/pvs, PV prefix talos-). Helm values committed at
   `../config/helm/csi-driver-nfs-values.yaml`.
7. Regenerated kubeconfig with `talosctl kubeconfig` and stored the fresh
   admin talosconfig in the password manager the same day.

## 3. Verification checklist (all passed on 2026-11-14/15)

1. `talosctl version` answers for all five nodes (client 1.12.2 vs server
   1.12.0 skew warning is cosmetic).
2. `kubectl get nodes -o wide` shows 5 Ready nodes, v1.35.0, Talos v1.12.0.
3. `kubectl get sc` shows nfs-retain. `kubectl get pods -A` all Running
   except the known homepage drift.
4. `helm list -A` shows cert-manager, metallb, traefik, csi-driver-nfs.
5. LAN probe `http://10.0.0.71:31622/` returns 200 (it-tools NodePort).
6. Public probe `https://it-tools.romeobag.ai/` returns the NetBird 401 PIN
   page (auth gate live).
7. Firewall rules survived qmrestore, but check anyway with
   `qm firewall rules list <vmid>`.

## 4. Traps that burned hours (remember these)

1. PBS restore through the PVE API needs the volid form
   `STORAGE:backup/vm/<vmid>/<stamp>` even though the on-disk layout has no
   backup directory. Disk resize is PUT /qemu/{id}/resize, POST returns 501.
   `PUT config` success returns data:null, never read null as failure.
2. Talos embeds qemu-guest-agent but it is sandboxed to its own container
   overlay, so file-read cannot reach /system/state (certcache) or host /etc,
   and PVE exec-sync 501s on Talos guests. Verify node networking by reading
   /proc/net/fib_trie and /proc/net/route via agent file-read. Set
   `agent enabled=1` on restored VMs.
3. csi-driver-nfs moved to the kubernetes-csi org (old chart repo URL 404s)
   and in chart 4.x `archiveOnDelete` is not a StorageClass parameter anymore
   (provisioner rejects the SC with InvalidArgument). StorageClass parameters
   are immutable, so a wrong SC is delete plus reinstall, not upgrade.
4. The Omni DB was orphaned-empty at one point because v1.9.3 moved the etcd
   data path (./data:/var/lib/etcd to ./etcd). An empty Omni is not the same
   as an outdated Omni, search other admin machines for a talosconfig file
   before doing anything drastic.
5. `kubectl get pvc,pv,sc -A` right after kubeconfig export. If it is empty
   the cluster never used PVs and the "salvage the old NFS data" hunt is moot.
6. RAM is the binding constraint on these hosts. CP 4 GiB times three plus
   workers 8 GiB times two plus co-residents, watch qemu RSS, balloon=0 is
   deliberate.
