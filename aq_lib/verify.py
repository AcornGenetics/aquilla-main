"""Device-side certificate verification against acorn-ca ``POST /renew`` (#242).

The Sentri presents its installed Device Certificate over mTLS to ``/renew`` to
prove the certificate authenticates and that mTLS is enforced. This runs on the
device: it presents the cert as a TLS client credential and needs no AWS
credentials. A missing/expired/wrong-CA certificate fails the TLS handshake and
nothing is renewed.
"""
import requests

from aq_lib.device_csr import generate_device_csr


class VerificationError(RuntimeError):
    """The certificate did not authenticate against /renew."""


def verify_renew(renew_endpoint, *, cert_path, key_path, device_id, http_post=None):
    """Present the Device Certificate over mTLS to ``/renew``; return the renewed cert.

    Builds a CSR with ``CN=device_id`` (renew requires the CSR CN to match the
    client cert CN) and POSTs it presenting ``cert=(cert_path, key_path)``.
    """
    if http_post is None:  # pragma: no cover - real network default
        http_post = requests.post

    _key_pem, csr_pem = generate_device_csr(device_id)
    try:
        response = http_post(renew_endpoint, data=csr_pem, cert=(cert_path, key_path))
    except requests.exceptions.SSLError as exc:
        raise VerificationError(f"mTLS handshake rejected: {exc}") from exc

    if response.status_code != 200:
        raise VerificationError(
            f"renew rejected the certificate: HTTP {response.status_code} "
            f"{response.json().get('error', '')}".strip()
        )
    return response.json()["certificate"]
