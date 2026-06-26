"""
Unit tests for operator-side device enrollment against acorn-ca /enroll (#240).

The operator (with AWS creds) SigV4-POSTs a Sentri's CSR to acorn-ca /enroll and
gets back the Device Certificate. The Pi makes no AWS call. Network boundary is
injected/mocked; no real AWS.
"""
import pytest
from botocore.credentials import Credentials

from aq_lib.enroll import (
    EnrollmentDenied,
    EnrollmentError,
    device_env_after_enroll,
    enroll,
)

DUMMY_CREDS = Credentials("AKIDEXAMPLE", "secret")
ENDPOINT = "https://rf2f9a0wie.execute-api.us-east-2.amazonaws.com/enroll"
CSR_PEM = "-----BEGIN CERTIFICATE REQUEST-----\nMIIB...\n-----END CERTIFICATE REQUEST-----\n"
CERT_PEM = "-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----\n"


class FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body

    def json(self):
        return self._json


class TestEnroll:
    def test_returns_the_certificate_on_200(self):
        def fake_post(url, data=None, headers=None):
            return FakeResponse(200, {"certificate": CERT_PEM})

        cert = enroll(
            CSR_PEM, ENDPOINT, region="us-east-2",
            credentials=DUMMY_CREDS, http_post=fake_post,
        )
        assert cert == CERT_PEM

    def test_posts_the_csr_body_sigv4_signed_to_enroll(self):
        captured = {}

        def fake_post(url, data=None, headers=None):
            captured.update(url=url, data=data, headers=headers)
            return FakeResponse(200, {"certificate": CERT_PEM})

        enroll(
            CSR_PEM, ENDPOINT, region="us-east-2",
            credentials=DUMMY_CREDS, http_post=fake_post,
        )

        assert captured["url"] == ENDPOINT
        assert captured["data"] == CSR_PEM
        # SigV4 over the execute-api service in the given region.
        auth = captured["headers"]["Authorization"]
        assert auth.startswith("AWS4-HMAC-SHA256")
        assert "/us-east-2/execute-api/aws4_request" in auth

    def test_revoked_device_raises_enrollment_denied(self):
        # acorn-ca returns 403 for a revoked Device ID — provisioning must stop
        # loudly, not write a non-cert as if it were a certificate.
        def fake_post(url, data=None, headers=None):
            return FakeResponse(403, {"error": "Device ID 10000000a6b7d43e is revoked"})

        with pytest.raises(EnrollmentDenied) as exc:
            enroll(
                CSR_PEM, ENDPOINT, region="us-east-2",
                credentials=DUMMY_CREDS, http_post=fake_post,
            )
        assert "revoked" in str(exc.value)

    def test_malformed_csr_400_raises_enrollment_error(self):
        # Any other non-200 (e.g. 400 malformed Device ID) also fails loudly,
        # carrying the status so the operator can see what happened.
        def fake_post(url, data=None, headers=None):
            return FakeResponse(400, {"error": "malformed Device ID: nope"})

        with pytest.raises(EnrollmentError) as exc:
            enroll(
                CSR_PEM, ENDPOINT, region="us-east-2",
                credentials=DUMMY_CREDS, http_post=fake_post,
            )
        assert "400" in str(exc.value)


class TestDeviceEnvAfterEnroll:
    def test_adds_cert_and_key_paths_and_drops_the_api_key(self):
        env = (
            "DEVICE_ID=10000000a6b7d43e\n"
            "AQ_SYNC_ENDPOINT=https://ingest.example\n"
            "AQ_SYNC_API_KEY=old-fleet-secret\n"
        )
        out = device_env_after_enroll(
            env,
            cert_path="/opt/aquila/config/device.crt",
            key_path="/opt/aquila/config/device.key",
        )
        lines = out.splitlines()

        # The retired Fleet API Key is gone entirely.
        assert not any(line.startswith("AQ_SYNC_API_KEY") for line in lines)
        # The Device Certificate paths are recorded for the Sync client (#241).
        assert "AQ_SYNC_CLIENT_CERT=/opt/aquila/config/device.crt" in lines
        assert "AQ_SYNC_CLIENT_KEY=/opt/aquila/config/device.key" in lines
        # Unrelated config is preserved.
        assert "DEVICE_ID=10000000a6b7d43e" in lines
        assert "AQ_SYNC_ENDPOINT=https://ingest.example" in lines
