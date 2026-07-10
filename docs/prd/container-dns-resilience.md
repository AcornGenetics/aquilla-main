# PRD: Container DNS Resilience for the Sentri Fleet

- **Status:** Draft
- **Author:** (owner TBD)
- **Date:** 2026-07-10
- **Related:** ADR-013 (mTLS ingest), ADR-001 (hostname-keyed device config), `fleet-config/docker-compose.yml`, `aquila_web/sync.py`

---

## 1. Summary

Fleet devices run their application in Docker containers that talk to the cloud
(analytics **ingest**, cert **renew**, and GHCR for **OTA**) *by hostname*. Today
the containers have no pinned DNS configuration, so Docker freezes whatever host
resolver existed when the container network was created. When the host's DNS
later changes — which it does routinely, because Tailscale MagicDNS manages the
host's `/etc/resolv.conf` — the container is left pointing at a stale resolver
and **all name resolution inside the container fails silently**. Runs stop syncing
to the Warehouse, certificate auto-renewal is at risk, and OTA image pulls can
fail, with no operator-visible signal.

This PRD proposes making container DNS **deterministic and environment-adaptive**
so devices resolve reliably across our network, customer sites, and Tailscale —
and proposes surfacing sync/DNS health so this class of failure can never again
go unnoticed.

## 2. Problem & Evidence

Observed on **sn06** (device id `1000000012d6b2cc`) on 2026-07-10:

- **Zero runs from sn06 have ever reached the Warehouse.** `fact_run` contains no
  rows for this device. The local outbox (`/opt/aquila/data/db/app.db`) holds
  **4 `run_complete` events, all pending (`synced_at IS NULL`)**, oldest dated
  Jul 2 — including today's run. No data is lost, but nothing has ever synced.
- **The backend container cannot resolve any hostname.** From inside
  `aquila-backend`, `ingest.cloud.acorngenetics.com`, `renew.cloud.acorngenetics.com`,
  and `google.com` all fail. From the **Pi host**, all three resolve correctly.
- **Root cause:** the container forwards DNS to Docker's embedded resolver
  (`127.0.0.11`), which forwards to the upstream Docker captured at network
  creation — `192.168.1.1`. The host, however, is now managed by Tailscale
  (`nameserver 100.100.100.100`) and no longer uses `192.168.1.1`. The captured
  upstream is stale/unreachable from the container, so lookups time out with
  `Temporary failure in name resolution`.
- **The application behaves correctly** — `sync.py` logs `Sync failed (will retry
  next interval)` and retains events as pending. The defect is purely in
  container DNS configuration, not app logic.
- **The cert is valid** (issuer `Sentri Fleet Root CA`, notAfter Jul 15 2026), so
  mTLS is *not* the cause — the container never resolves far enough to use it.

### Why this is a fleet-wide, recurring risk

- Only **3 device ids** have ever appeared in `fact_run`; others (like sn06) have
  silently never synced. Whether a device works depends on *which resolver Docker
  happened to capture* when its network was created — pure timing relative to the
  Tailscale DNS takeover, not correctness.
- The captured value is **re-rolled by ordinary events**: OTA updates recreate
  containers (Watchtower), reboots re-establish networking, Tailscale updates
  rewrite host DNS, and site/network changes move the upstream. A device that
  works today can flip to broken on the next update — non-deterministically.

## 3. Goals

1. Containers resolve `ingest`, `renew`, and `ghcr.io` reliably **regardless of
   host-DNS changes** (Tailscale, reboots, OTA container recreation).
2. Resolution works **at customer sites we do not control**, including networks
   that block outbound DNS (port 53) to external resolvers and mandate their own.
3. Preserve ability to resolve **private / Tailscale (`*.ts.net`) names** from
   containers where needed.
4. **No silent failures:** sync/DNS health is observable at the fleet level so a
   stuck device is detected quickly, not weeks later.

## 4. Non-Goals

- Changing cloud endpoints, the mTLS ingest design (ADR-013), or the cert PKI.
- Replacing or reconfiguring Tailscale itself.
- Any change to `sync.py` retry/outbox semantics (they already behave correctly).

## 5. Options Considered

### Option A — Pin public DNS in compose (`dns: [1.1.1.1, 8.8.8.8]`)
- **Pros:** one-line change to `fleet-config/docker-compose.yml`; no host packages;
  removes the stale-capture failure immediately; deterministic.
- **Cons:** breaks at customer sites that block external DNS (53) and force a local
  resolver; cannot resolve private/Tailscale names; leaks queried hostnames to a
  third party (names only — payloads remain TLS-encrypted).
- **Fit:** good *interim* fix if we control every network the fleet runs on.

### Option B — Host-side forwarder + container DNS → host (Recommended)
Run a lightweight forwarder (`dnsmasq`) on each Pi host, listening on the Docker
bridge gateway (`172.18.0.1` for `fleet_default`), forwarding to whatever resolver
the host currently uses. Set container `dns: [172.18.0.1, 1.1.1.1]` (host first,
public as last-resort fallback).
- **Pros:** containers inherit the host's *current, correct* DNS for whatever
  network they're on — customer resolver at a customer site, Tailscale on ours,
  including split-horizon/private names; adapts automatically; public fallback for
  degraded cases.
- **Cons:** adds a host service to install, run, and monitor; must forward to the
  host's *real* upstreams (avoid self-referential loops); binds to a Docker bridge
  address that only exists after Docker is up (startup ordering); if the forwarder
  dies, all containers lose DNS at once.
- **Fit:** the deploy-anywhere fix for fleets on uncontrolled networks.

### Option C — `network_mode: host` for cloud-talking containers
- **Pros:** container uses the host's `/etc/resolv.conf` directly; no extra service.
- **Cons:** breaks Docker service-name networking (`aquila-backend:8090`), port
  mapping, and isolation the compose relies on. Too invasive. **Rejected.**

## 6. Recommendation

Adopt **Option B** as the durable fix, with **Option A** available as an immediate
stopgap on controlled networks. Gate the final choice on the deployment question in
§10 (will devices run at customer sites we don't control?). If yes → Option B.

## 7. Requirements

### Functional
- FR1: Provision a forwarding resolver on each device host, bound to the
  `fleet_default` bridge gateway, forwarding to the host's active upstream(s).
- FR2: Configure `backend`, `app`, and `watchtower` services with
  `dns: [<host-bridge-ip>, 1.1.1.1]`. (`ui` serves static assets only — no
  outbound calls — and can be left unchanged.)
- FR3: Forwarder config must derive upstreams from the live host resolver, not a
  hardcoded server, and must be loop-safe.
- FR4: Ordering — the forwarder must be available before/independently of the app
  containers; container DNS must degrade to the public fallback if the forwarder
  is briefly unavailable.

### Observability (closes the "silent" gap)
- FR5: Expose per-device sync health so a device that hasn't synced recently is
  visibly flagged (e.g. a fleet view over the Warehouse `fact_run` last-run
  timestamp, and/or the local outbox pending-event depth). Surfacing candidates:
  `acorn-internal-app` fleet view; a device health metric; or a scheduled check.

### Verification
- FR6: A device-side check confirming the container can resolve `ingest`, `renew`,
  and `ghcr.io` (read-only, non-disruptive), runnable in each target network.
- FR7: Post-fix, confirm queued outbox events flush to `fact_run` automatically
  (no manual re-send) once resolution is restored.

## 8. Rollout & Migration

1. Land the forwarder provisioning in `setup_fleet_device.sh` / `deployment2.sh`
   and the `dns:` entries in `fleet-config/docker-compose.yml` (repo change; review
   before any device touch).
2. Apply per device by recreating containers (`docker compose up -d`) — **this
   restarts containers, so schedule around active runs** (do not disturb a running
   assay).
3. On restore, the existing 15-minute retry loop flushes all pending outbox events
   automatically; verify backlog (e.g. sn06's 4 events) lands in `fact_run`.
4. Backfill audit: cross-check every device's last-sync in the Warehouse to find
   others silently stuck like sn06, and remediate.

## 9. Risks & Mitigations

- **Forwarder is a new single point of failure per device** → public fallback in
  the `dns:` list; restart policy; include in device health checks.
- **DNS loop misconfiguration** → forwarder must target real upstreams, not itself;
  add a provisioning test / validation.
- **Startup ordering (bridge IP not yet present)** → validate bind timing; rely on
  the public fallback during the brief window.
- **Config regression** → extend `tests/fleet_device/test_compose_config.py` to
  assert the `dns:` entries exist on `backend`/`app`/`watchtower`.

## 10. Success Metrics

- 100% of active devices show a Warehouse `fact_run` entry within one sync interval
  of a completed run.
- Container resolves `ingest` / `renew` / `ghcr.io` in every target network,
  including at least one site that blocks external DNS.
- Cert auto-renewals succeed fleet-wide (no lapses).
- Time-to-detect a stuck/non-syncing device drops from "weeks / manual" to
  "same day / automatic."

## 11. Open Questions

1. **Deployment reality:** will devices run at customer sites on networks we do not
   control? (Decides A vs B.)
2. **Privacy posture:** is leaking queried hostnames to a public resolver
   acceptable, or do we want DoH/DoT / a private-only path?
3. **Observability owner:** does fleet sync-health live in `acorn-internal-app`, a
   device metric, or a scheduled job — and who owns the alert?
4. **Tailscale name dependency:** do any containers need to resolve `*.ts.net`
   today, or only public cloud endpoints? (Affects how strictly Option B is needed.)
