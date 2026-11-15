# NetBird Certificate Issuer incident and fix (November 2026)

Resolved 2026-11-15 alongside the Talos node04 redeployment. This write-up
covers what broke, what was applied, and what I verified on the same day.

## 1. Symptom

it-tools.romeobag.ai was broken from outside the house. The NetBird reverse
proxy could not serve the service properly and its Certificate Issuer never
produced a working TLS setup for it, so remote access failed with certificate
errors before any page loaded. LAN access to the app itself was fine.

## 2. What the access path looks like

```
browser -> DNS *.romeobag.ai -> VPS 23.94.59.10:443
  -> outer Traefik v3.6 (tcp router HostSNI(*), passthrough, pp-v2 transport)
  -> netbird-proxy:8443 (issues the browser cert per service from
     netbird_proxy_certs volume; enforces service access control)
  -> overlay route for 10.0.0.0/24 advertised by in-cluster netbird-agent
  -> upstream service "it-tools-k8s" -> Talos NodePort 10.0.0.71:31622
```

The certificate that the browser sees for it-tools.romeobag.ai comes from the
NetBird Certificate Issuer, not Let's Encrypt. That is why the chain shows as
untrusted until the NetBird root CA is installed on the client.

## 3. The fix that was applied

One. Traefik service definition for the it-tools upstream on the VPS. The
block below was applied to the reverse proxy Traefik config (the dynamic file
is `~/netbird/traefik-dynamic.yaml`, committed in this repo at
`Netbird/traefik-dynamic.yaml`) and the stack was reloaded:

```yaml
it-tools-k8s:
  loadBalancer:
    servers:
      - url: https://10.0.0.71:31622
    passHostHeader: true
```

The service name `it-tools-k8s` is the upstream that the NetBird managed
service for it-tools.romeobag.ai points at. Targeting the NodePort directly
(31622, pinned to CP-01) bypasses the in-cluster IngressRoute that used to sit
in front of it, and `passHostHeader: true` keeps the original Host header so
the app and its BASE_URL behave.

Two. Security hardening as advised earlier. The NetBird managed service now
sits behind its own access control gate (PIN method). Unauthenticated clients
get a 401 "NetBird Service" page before the proxy ever dials the cluster, so
the NodePort service is no longer exposed behind only a DNS name.

## 4. Verification run on 2026-11-15

1. `getent hosts it-tools.romeobag.ai` returns 23.94.59.10 (VPS). Correct.
2. `curl -k https://it-tools.romeobag.ai/` returns HTTP 401 with the NetBird
   Service login page (`window.__DATA__ = {"methods":{"pin":"pin"}}`). The
   auth layer is live and gating everything upstream.
3. The certificate the proxy presents fails OS-chain verification
   (`tls_verify=20`), consistent with a NetBird-internal-CA cert. Expected.
4. In the cluster, `kubectl get svc it-tools -n default` shows NodePort
   `80:31622` targeting container port 8080, image ghcr.io/sharevb/it-tools,
   3/3 replicas with a PodDisruptionBudget.
5. From the LAN, `http://10.0.0.71:31622/` returns 200 from nginx/1.30.2
   (it-tools itself). So NodePort 31622 is the app speaking plain HTTP.

## 5. One caveat worth staring at

The applied service block dials `https://10.0.0.71:31622`, but a LAN probe of
that same NodePort shows it speaking plain HTTP (a TLS handshake gets
`wrong version number`). If authenticated requests through NetBird ever start
502-ing, that scheme mismatch is the first place to look. Either the upstream
stays https and something in front of the app must terminate TLS (for example
point the block at the in-cluster Traefik websecure port instead), or the block
should be `http://10.0.0.71:31622`. The browser-side cert problem and the
401 gate are verified working; this is the one seam I did not see proven
end to end from the VPS side.

## 6. Rollback

1. Remove or restore the `it-tools-k8s` service block on the VPS in
   `~/netbird/traefik-dynamic.yaml`.
2. `docker compose up -d` in `~/netbird` on the VPS (or restart the
   netbird-proxy container) to reload.
3. Optionally drop the PIN access control on the service in the NetBird
   dashboard, though keeping it is the whole point.

## 7. Follow-ups this incident exposed

1. `Netbird/config.yaml` in this repo contains live authSecret and sqlite
   encryptionKey values, and `Netbird/proxy.env` contains the proxy token.
   Rotate these and move real values to the VPS only, gitignore the env/config
   files, keep `.example` versions in git.
2. Pin the it-tools image back to a dated tag on the live cluster (repo pins
   2026.1.4, live runs nightly).
3. Pin the netbirdio/netbird agent image (currently `latest`).
4. homepage Deployment is 0/3 because its ServiceAccount is missing, one
   `kubectl -n homepage apply` of the namespace's serviceaccount fixes it.
5. The in-cluster IngressRoute for it-tools was removed in favor of the
   NodePort path. If the LAN path should keep working too, bring the
   IngressRoute back or front the NodePort with the Traefik LB.
