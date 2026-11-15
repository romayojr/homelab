# Talos machine config custody

There are no machine configs in this folder on purpose. A Talos machine config
embeds the cluster CA material, so committing one is committing the cluster's
crown jewels. What lives where:

1. Omni (VM 706, http://10.0.0.70, https://omni.local.romeobagay.com) holds
   the applied machine configs and admin certs for the enrolled cluster.
2. talosconfig files live on admin machines (`~/.talos/config`) and in the
   password manager. The current admin cert expires 2027-01-11. Renew with
   `talosctl certificates renew` and store the fresh file immediately.
3. The PVE cloud-init layer (ipconfig0 static IPs, ciuser, sshkeys) lives in
   the VM configs on proxmox-node04, not here.

Regenerating a full set for a fresh bootstrap:

```
talosctl gen config talos-proxmox-cluster https://10.0.0.71:6443 \
  --output-dir ./gen --with-extras kubernetes
```

Then wire in the homelab specifics before bootstrapping. Node IPs must match
the static PVE cloud-init addresses (.71-.75) because machine configs embed
endpoints. Keep the Talos installer/image version consistent with the running
nodes (v1.12.0 as of 2026-11-15, check with `talosctl version`). Apply via
Omni for enrolled machines, or `talosctl apply-config --insecure` for cold
rebuilds.

Recovering admin access when talosconfig is lost, in order of cheapness:

1. Search every admin machine for an older talosconfig, stale ones stay valid
   for months and the version handshake warning is cosmetic.
2. Omni. The DB holds machine configs and can mint new auth. If Omni shows 0
   machines after a version change, suspect an orphaned etcd data path
   (v1.9.3 moved the etcd directory) before declaring the DB empty.
3. Offline last resort. Full-clone a CP disk, mount the STATE partition
   read-only on any Linux VM, read certcache for the OS CA key, and sign a new
   admin client cert (CN=admin, O=os:users) with openssl. The sandboxed guest
   agent cannot read certcache from inside a running Talos node.
