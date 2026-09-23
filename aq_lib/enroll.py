"""Operator-side device enrollment against acorn-ca ``POST /enroll`` (#240).

The operator (holding AWS credentials) SigV4-signs a POST of a Sentri's CSR to
acorn-ca's IAM-authorized ``/enroll`` endpoint and receives the Device
Certificate. The Pi never holds AWS credentials — this runs on the operator's
machine; the issued certificate is installed back onto the Pi separately.
"""
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

SERVICE = "execute-api"


class EnrollmentError(RuntimeError):
    """Enrollment failed — provisioning must stop, no certificate was issued."""


class EnrollmentDenied(EnrollmentError):
    """acorn-ca refused to issue (e.g. the Device ID is revoked — HTTP 403)."""


def enroll(csr_pem, endpoint, *, region, credentials, http_post=None):
    """Enrol a CSR and return the Device Certificate PEM to install as device.crt.

    SigV4-signs a POST of ``csr_pem`` to ``endpoint``. When acorn-ca returns the
    signing CA alongside the leaf (``caCertificate``, acorn-ca#48), returns the
    ``leaf + CA`` chain so device.crt lets AWS IoT JITP match the registered CA on
    first connect; otherwise returns the leaf alone (older CA — unchanged).
    """
    if http_post is None:  # pragma: no cover - real network default
        import requests

        http_post = requests.post

    request = AWSRequest(method="POST", url=endpoint, data=csr_pem)
    SigV4Auth(credentials, SERVICE, region).add_auth(request)

    response = http_post(endpoint, data=csr_pem, headers=dict(request.headers))

    if response.status_code == 403:
        raise EnrollmentDenied(_error_message(response))
    if response.status_code != 200:
        raise EnrollmentError(
            f"enroll failed: HTTP {response.status_code} {_error_message(response)}".strip()
        )
    body = response.json()
    leaf = body["certificate"]
    # acorn-ca#48 returns the signing CA alongside the leaf. device.crt must be
    # leaf + CA so AWS IoT JITP can match the registered CA from the chain the
    # device presents on first connect. Absent (older CA) -> leaf only, as before.
    ca = body.get("caCertificate")
    if not ca:
        return leaf
    chain = leaf.rstrip() + "\n" + ca.strip() + "\n"
    return chain


def _error_message(response):
    try:
        return response.json().get("error", "")
    except Exception:
        return ""


CERT_ENV_VAR = "AQ_SYNC_CLIENT_CERT"
KEY_ENV_VAR = "AQ_SYNC_CLIENT_KEY"
RETIRED_VAR = "AQ_SYNC_API_KEY"


def device_env_after_enroll(env_text, *, cert_path, key_path):
    """Return ``device.env`` updated to use the Device Certificate.

    Records the cert/key paths the Sync client reads (#241) and removes the
    retired Fleet API Key. All other lines are preserved in order.
    """
    managed = {CERT_ENV_VAR, KEY_ENV_VAR, RETIRED_VAR}
    kept = [
        line
        for line in env_text.splitlines()
        if line.split("=", 1)[0] not in managed
    ]
    kept.append(f"{CERT_ENV_VAR}={cert_path}")
    kept.append(f"{KEY_ENV_VAR}={key_path}")
    return "\n".join(kept) + "\n"
