"""
Unit tests for device-side certificate verification against acorn-ca /renew (#242).

The Sentri presents its installed Device Certificate over mTLS to /renew to prove
the certificate authenticates and that mTLS is enforced. Network boundary is
injected/mocked; no real TLS.
"""
import pytest
import requests
from cryptography import x509
from cryptography.x509.oid import NameOID

from aq_lib.verify import VerificationError, verify_renew

RENEW_ENDPOINT = "https://renew.example/renew"
CERT_PATH = "/opt/aquila/config/device.crt"
KEY_PATH = "/opt/aquila/config/device.key"
DEVICE_ID = "10000000a6b7d43e"
RENEWED_PEM = "-----BEGIN CERTIFICATE-----\nMIIRENEWED\n-----END CERTIFICATE-----\n"


class FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body

    def json(self):
        return self._json


class TestVerifyRenew:
    def test_presents_cert_and_csr_and_returns_renewed_cert_on_200(self):
        captured = {}

        def fake_post(url, data=None, cert=None):
            captured.update(url=url, data=data, cert=cert)
            return FakeResponse(200, {"certificate": RENEWED_PEM})

        cert = verify_renew(
            RENEW_ENDPOINT, cert_path=CERT_PATH, key_path=KEY_PATH,
            device_id=DEVICE_ID, http_post=fake_post,
        )

        assert cert == RENEWED_PEM
        # The Device Certificate is presented for the mTLS handshake...
        assert captured["cert"] == (CERT_PATH, KEY_PATH)
        assert captured["url"] == RENEW_ENDPOINT
        # ...alongside a CSR whose CN matches the cert identity (renew requires it).
        csr = x509.load_pem_x509_csr(
            captured["data"] if isinstance(captured["data"], bytes) else captured["data"].encode()
        )
        (cn,) = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert cn.value == DEVICE_ID

    def test_tls_handshake_rejection_raises_verification_error(self):
        # A missing/expired/wrong-CA client cert is rejected at the TLS layer —
        # requests surfaces that as SSLError. Verification must fail clearly, not
        # leak a raw SSL traceback.
        def fake_post(url, data=None, cert=None):
            raise requests.exceptions.SSLError("certificate verify failed")

        with pytest.raises(VerificationError) as exc:
            verify_renew(
                RENEW_ENDPOINT, cert_path=CERT_PATH, key_path=KEY_PATH,
                device_id=DEVICE_ID, http_post=fake_post,
            )
        assert "handshake" in str(exc.value).lower()

    def test_non_200_response_raises_verification_error_with_status(self):
        # The handshake succeeded but the app rejected it (e.g. 403 CN mismatch).
        # Still a verification failure, surfaced with the status.
        def fake_post(url, data=None, cert=None):
            return FakeResponse(403, {"error": "mTLS client certificate required"})

        with pytest.raises(VerificationError) as exc:
            verify_renew(
                RENEW_ENDPOINT, cert_path=CERT_PATH, key_path=KEY_PATH,
                device_id=DEVICE_ID, http_post=fake_post,
            )
        assert "403" in str(exc.value)
