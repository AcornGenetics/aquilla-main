"""Entry point for the Profile Sync Agent Greengrass component (ADR-022, am#488).

Wires the unit-tested core — `load_config`, `ProfileSyncAgent`, `SyncCoordinator` —
to Greengrass IPC and S3, and drives a reconcile on **startup**, on a
**`profiles`-shadow delta**, and on a **periodic interval** backstop.

Runs in the com.acorn.profile-sync component — its own container, REUSING the
aquilla-main-api image, with `network_mode: host` so boto3 reaches the Token Exchange
Role creds endpoint on the host loopback (a bridge-networked container can't). Started
by the recipe's Run: `python -m aquila_web.profile_sync_main`.

This module is glue (IPC client, boto3, the run loop) — verified on a real Sentri
(#468), not in unit tests, exactly like `start_update_agent`. The decisions it wires
together are what carry the tests.
"""
import logging
import time

from aquila_web.greengrass_ipc import GreengrassIpc
from aquila_web.profile_sync_agent import ProfileSyncAgent, SyncCoordinator
from aquila_web.profile_sync_config import load_config

log = logging.getLogger("profile_sync")

SHADOW_NAME = "profiles"


def _s3_io(bucket):
    """Build the (fetch, remote_version) callables reconcile() needs, over boto3.

    boto3 picks up the Token Exchange Role credentials from the environment
    Greengrass sets on the component — which works because this runs on the host,
    not in the bridge-networked container (the whole point of ADR-022).
    """
    import boto3

    s3 = boto3.client("s3")

    def fetch(key):
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()

    def remote_version(key):
        # S3 version marker — reconcile re-pulls a key whose body changed in place.
        return s3.head_object(Bucket=bucket, Key=key).get("VersionId")

    return fetch, remote_version


def main():
    logging.basicConfig(level=logging.INFO)
    cfg = load_config()  # raises with a clear message if PROFILES_BUCKET is missing

    ipc = GreengrassIpc()
    fetch, remote_version = _s3_io(cfg.bucket)
    agent = ProfileSyncAgent(ipc, cfg.managed_dir, fetch, remote_version)
    coordinator = SyncCoordinator(agent, log=log)

    log.info(
        "Profile Sync Agent starting: bucket=%s managed_dir=%s interval=%ss",
        cfg.bucket, cfg.managed_dir, cfg.interval_s,
    )

    # 1. Startup — reconcile once immediately (catches assignment changes made while
    #    the device was offline / the agent was down).
    coordinator.reconcile()

    # 2. React to assignment changes within seconds. Best-effort: if the subscribe
    #    fails, the interval backstop below still keeps the device in sync.
    try:
        ipc.subscribe_to_shadow_delta(SHADOW_NAME, coordinator.reconcile)
    except Exception as e:  # noqa: BLE001
        log.warning("profiles shadow-delta subscribe failed; relying on interval: %s", e)

    # 3. Interval backstop — the only trigger that catches an in-place S3 edit
    #    (same key, new version marker), which produces no shadow delta.
    while True:
        time.sleep(cfg.interval_s)
        coordinator.reconcile()


if __name__ == "__main__":
    main()
