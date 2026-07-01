"""Device-side Device Certificate auto-renewal (issue #279).

A Sentri renews its own short-lived Device Certificate before it expires. The
current cert is the credential: the device presents it over mTLS to acorn-ca
``POST /renew`` and, on success, installs a freshly-rotated keypair + cert
locally. This runs on the Pi, needs no operator and no AWS credentials, and is the
piece that closes the gap where enrolled devices otherwise ride a single fixed
cert until it expires.
"""
import datetime as dt
import os

import requests
from cryptography import x509

from aq_lib.device_csr import generate_device_csr

CERT_FILENAME = "device.crt"
KEY_FILENAME = "device.key"
ENV_FILENAME = "device.env"

# The prod acorn-ca renew front. device.env may override via AQ_RENEW_ENDPOINT.
DEFAULT_RENEW_ENDPOINT = "https://renew.cloud.acorngenetics.com/renew"

# Renew once the remaining lifetime drops below this fraction of the cert's total
# validity window — self-adjusts whether the leaf is 7 or 14 days.
DEFAULT_RENEW_AT = 1 / 3


class RenewalError(RuntimeError):
    """Renewal was due but could not be completed; the installed cert is unchanged."""


def renewal_due(cert_pem, *, now: dt.datetime, renew_at: float = DEFAULT_RENEW_AT) -> bool:
    """Is it time to renew ``cert_pem`` as of ``now``?

    True once the fraction of the certificate's validity window still remaining
    has fallen to ``renew_at`` or below.
    """
    cert = x509.load_pem_x509_certificate(
        cert_pem if isinstance(cert_pem, bytes) else cert_pem.encode()
    )
    not_before = cert.not_valid_before_utc
    not_after = cert.not_valid_after_utc

    total = not_after - not_before
    remaining = not_after - now
    return remaining <= renew_at * total


def renew_device_cert(
    renew_endpoint,
    *,
    config_dir,
    device_id,
    now: dt.datetime,
    http_post=None,
    renew_at: float = DEFAULT_RENEW_AT,
):
    """Renew the installed Device Certificate if it is due; otherwise do nothing.

    Reads the current cert/key from ``config_dir``. If renewal is not yet due,
    returns ``None`` without touching the network or disk. (Issuance + atomic
    install land in later slices.)
    """
    cert_path = os.path.join(config_dir, CERT_FILENAME)
    with open(cert_path, "rb") as f:
        cert_pem = f.read()

    if not renewal_due(cert_pem, now=now, renew_at=renew_at):
        return None

    if http_post is None:  # pragma: no cover - real network default
        http_post = requests.post

    key_path = os.path.join(config_dir, KEY_FILENAME)

    # Rotate: a fresh keypair each renewal. The new cert is bound to this key, so
    # both must be installed together or neither.
    new_key_pem, new_csr_pem = generate_device_csr(device_id)
    try:
        response = http_post(renew_endpoint, data=new_csr_pem, cert=(cert_path, key_path))
    except requests.exceptions.SSLError as exc:
        # The current cert was rejected at the TLS layer (lapsed/wrong-CA). Nothing
        # is installed; recovery is offline re-enrollment (a later slice).
        raise RenewalError(f"mTLS handshake rejected: {exc}") from exc
    if response.status_code != 200:
        raise RenewalError(
            f"renew rejected the certificate: HTTP {response.status_code} "
            f"{response.json().get('error', '')}".strip()
        )
    new_cert_pem = response.json()["certificate"]

    _install_pair(cert_path, new_cert_pem, key_path, new_key_pem)
    return new_cert_pem


def _write_0600(path, data: bytes):
    """Write ``data`` to ``path`` owner-only, atomically (temp file + rename)."""
    tmp = f"{path}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _install_pair(cert_path, cert_pem, key_path, key_pem):
    """Install the new key then the new cert, each 0600.

    The key is promoted first so a crash between the two renames leaves the new
    key with the old cert; either way the Sync client only ever loads files that
    were fully written (never a truncated one).
    """
    _write_0600(key_path, key_pem if isinstance(key_pem, bytes) else key_pem.encode())
    _write_0600(cert_path, cert_pem if isinstance(cert_pem, bytes) else cert_pem.encode())


def _read_env(config_dir):
    """Parse ``device.env`` (KEY=VALUE lines) into a dict."""
    values = {}
    with open(os.path.join(config_dir, ENV_FILENAME)) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    return values


def run_renewal(config_dir, *, now: dt.datetime = None, http_post=None):
    """On-device entrypoint: renew the installed cert using ``device.env`` config.

    Reads ``DEVICE_ID`` and the renew endpoint (``AQ_RENEW_ENDPOINT``, else the
    prod default) from ``config_dir/device.env`` and renews the installed cert in
    place. Returns the new cert PEM, or ``None`` if renewal was not yet due.
    """
    if now is None:
        now = dt.datetime.now(dt.timezone.utc)
    env = _read_env(config_dir)
    device_id = env.get("DEVICE_ID")
    if not device_id:
        raise RenewalError(f"no DEVICE_ID in {config_dir}/{ENV_FILENAME}")
    endpoint = env.get("AQ_RENEW_ENDPOINT") or DEFAULT_RENEW_ENDPOINT

    return renew_device_cert(
        endpoint, config_dir=config_dir, device_id=device_id,
        now=now, http_post=http_post,
    )


def main(argv=None):  # pragma: no cover - thin container/systemd entrypoint
    import sys

    config_dir = (argv or sys.argv[1:] or ["/config"])[0]
    try:
        new_cert = run_renewal(config_dir)
    except RenewalError as e:
        # Fail this run loudly so systemd records it; the next timer tick retries.
        # The installed cert is untouched, so the device keeps working until then.
        print(f"renewal failed: {e}", file=sys.stderr)
        return 1
    if new_cert is None:
        print("certificate not yet due for renewal — no action")
    else:
        print(f"renewed: installed new certificate at {config_dir}/{CERT_FILENAME}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
