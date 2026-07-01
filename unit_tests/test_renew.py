"""
Unit tests for device-side Device Certificate auto-renewal (aq_lib/renew.py, #279).

The Sentri renews its own short-lived Device Certificate before it expires: it
presents the current cert over mTLS to acorn-ca /renew, and on success installs a
freshly-rotated keypair + cert locally (0600). Runs on the Pi with no operator and
no AWS credentials — the current cert is the credential. Clock, network, and
filesystem are injected/tmp; no real TLS.
"""
import datetime as dt

import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from aq_lib.renew import RenewalError, renew_device_cert, renewal_due, run_renewal

DEVICE_ID = "10000000a6b7d43e"
RENEW_ENDPOINT = "https://renew.example/renew"


class FakeResponse:
    def __init__(self, status_code, json_body):
        self.status_code = status_code
        self._json = json_body

    def json(self):
        return self._json


def make_cert_pem(not_before: dt.datetime, not_after: dt.datetime, cn=DEVICE_ID) -> bytes:
    """A minimal self-signed leaf with the given validity window, for tests."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def make_keypair_pem():
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def write_config(config_dir, cert_pem, key_pem=None):
    """Lay down device.crt + device.key as an enrolled Pi would have them."""
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "device.crt").write_bytes(cert_pem)
    (config_dir / "device.key").write_bytes(key_pem or make_keypair_pem())


def due_cert(now):
    return make_cert_pem(
        not_before=now - dt.timedelta(days=10),
        not_after=now + dt.timedelta(days=4),
    )


def issuing_post(now):
    """A fake /renew that acts as the CA: signs a leaf for the CSR's public key.

    Records the request it saw in ``.seen`` so tests can assert what was sent.
    """
    seen = {}

    def post(url, data=None, cert=None):
        seen.update(url=url, data=data, cert=cert)
        csr = x509.load_pem_x509_csr(data if isinstance(data, bytes) else data.encode())
        ca_key = ec.generate_private_key(ec.SECP256R1())
        leaf = (
            x509.CertificateBuilder()
            .subject_name(csr.subject)
            .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")]))
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + dt.timedelta(days=14))
            .sign(ca_key, hashes.SHA256())
        )
        pem = leaf.public_bytes(serialization.Encoding.PEM).decode()
        seen["issued"] = pem
        return FakeResponse(200, {"certificate": pem})

    post.seen = seen
    return post


class TestRenewalDue:
    def test_not_due_when_plenty_of_lifetime_remains(self):
        # A 14-day cert one day old: ~13/14 of its life is left — well above the
        # 1/3-remaining threshold. Renewing now would be wasteful churn.
        now = dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc)
        cert = make_cert_pem(
            not_before=now - dt.timedelta(days=1),
            not_after=now + dt.timedelta(days=13),
        )
        assert renewal_due(cert, now=now) is False

    def test_due_once_remaining_lifetime_falls_below_the_threshold(self):
        # 14-day cert, 10 days elapsed: only 4 days (~2/7) of life remain, under
        # the 1/3 threshold — renew now, before it lapses.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        cert = make_cert_pem(
            not_before=now - dt.timedelta(days=10),
            not_after=now + dt.timedelta(days=4),
        )
        assert renewal_due(cert, now=now) is True

    def test_due_when_already_expired(self):
        # Past notAfter entirely (missed renewals): still "due" — the caller
        # should attempt renewal, though the handshake may now be rejected.
        now = dt.datetime(2026, 7, 20, tzinfo=dt.timezone.utc)
        cert = make_cert_pem(
            not_before=now - dt.timedelta(days=19),
            not_after=now - dt.timedelta(days=5),
        )
        assert renewal_due(cert, now=now) is True


class TestRenewDeviceCert:
    def test_no_op_when_not_yet_due(self, tmp_path):
        # Cert is young: renewal must not fire, must not touch the network, and
        # must leave the installed cert/key exactly as they were.
        now = dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        fresh = make_cert_pem(
            not_before=now - dt.timedelta(days=1),
            not_after=now + dt.timedelta(days=13),
        )
        write_config(config, fresh)
        before_crt = (config / "device.crt").read_bytes()
        before_key = (config / "device.key").read_bytes()

        def exploding_post(*a, **k):
            raise AssertionError("must not contact /renew when not due")

        result = renew_device_cert(
            RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
            now=now, http_post=exploding_post,
        )

        assert result is None
        assert (config / "device.crt").read_bytes() == before_crt
        assert (config / "device.key").read_bytes() == before_key

    def test_installs_rotated_key_and_matching_cert_on_success(self, tmp_path):
        # Due for renewal. /renew issues a cert for the CSR's (freshly rotated)
        # public key. After renewal the installed key must be the NEW one and the
        # installed cert the CA's cert for it — a consistent pair, 0600.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        old_key = make_keypair_pem()
        write_config(config, due_cert(now), key_pem=old_key)
        post = issuing_post(now)

        returned = renew_device_cert(
            RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
            now=now, http_post=post,
        )

        installed_crt = (config / "device.crt").read_bytes()
        installed_key = (config / "device.key").read_bytes()

        # The CA's freshly-issued cert is what's now installed, and returned.
        assert installed_crt.decode() == post.seen["issued"]
        assert returned == post.seen["issued"]
        # The private key was rotated — the old key is gone.
        assert installed_key != old_key
        # Installed cert and installed key are a matching pair.
        cert_obj = x509.load_pem_x509_certificate(installed_crt)
        key_obj = serialization.load_pem_private_key(installed_key, password=None)
        assert cert_obj.public_key().public_numbers() == key_obj.public_key().public_numbers()
        # Both remain owner-only on the Pi.
        assert (config / "device.crt").stat().st_mode & 0o777 == 0o600
        assert (config / "device.key").stat().st_mode & 0o777 == 0o600

    def test_non_200_raises_and_leaves_the_installed_pair_intact(self, tmp_path):
        # Due, but /renew refuses (e.g. 403 CN mismatch / revoked). The device
        # must keep its current valid cert+key untouched and retry next tick —
        # never half-install the freshly-rotated key.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))
        before_crt = (config / "device.crt").read_bytes()
        before_key = (config / "device.key").read_bytes()

        def refusing_post(url, data=None, cert=None):
            return FakeResponse(403, {"error": "Device ID is revoked"})

        with pytest.raises(RenewalError) as exc:
            renew_device_cert(
                RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
                now=now, http_post=refusing_post,
            )

        assert "403" in str(exc.value)
        assert (config / "device.crt").read_bytes() == before_crt
        assert (config / "device.key").read_bytes() == before_key

    def test_tls_handshake_rejection_raises_and_leaves_pair_intact(self, tmp_path):
        # The cert lapsed before we renewed: /renew rejects it at the TLS layer.
        # Surface a clear RenewalError (not a raw SSLError) and leave disk intact —
        # recovery is offline re-enrollment, a later slice.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))
        before_crt = (config / "device.crt").read_bytes()
        before_key = (config / "device.key").read_bytes()

        def rejecting_post(url, data=None, cert=None):
            raise requests.exceptions.SSLError("certificate verify failed")

        with pytest.raises(RenewalError) as exc:
            renew_device_cert(
                RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
                now=now, http_post=rejecting_post,
            )

        assert "handshake" in str(exc.value).lower()
        assert (config / "device.crt").read_bytes() == before_crt
        assert (config / "device.key").read_bytes() == before_key

    def test_presents_current_cert_and_csr_cn_matches_device_id(self, tmp_path):
        # The mTLS credential is the CURRENT installed cert/key, and the CSR CN
        # must equal the Device ID — /renew rejects a CSR whose CN differs from
        # the client cert's CN.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))
        post = issuing_post(now)

        renew_device_cert(
            RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
            now=now, http_post=post,
        )

        assert post.seen["url"] == RENEW_ENDPOINT
        assert post.seen["cert"] == (
            str(config / "device.crt"), str(config / "device.key"),
        )
        sent_csr = post.seen["data"]
        csr = x509.load_pem_x509_csr(
            sent_csr if isinstance(sent_csr, bytes) else sent_csr.encode()
        )
        (cn,) = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert cn.value == DEVICE_ID


class TestRunRenewal:
    def test_reads_device_id_and_endpoint_from_device_env_and_renews(self, tmp_path):
        # The on-device entrypoint (run in the app image by the systemd timer) takes
        # only the config dir: it reads DEVICE_ID + the renew endpoint from
        # device.env and renews the installed cert in place.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))
        (config / "device.env").write_text(
            f"DEVICE_ID={DEVICE_ID}\n"
            "AQ_RENEW_ENDPOINT=https://renew.example/renew\n"
            "AQ_SYNC_ENDPOINT=https://ingest.example\n"
        )
        post = issuing_post(now)

        result = run_renewal(str(config), now=now, http_post=post)

        # It renewed: the request went to the endpoint from device.env, under the
        # DEVICE_ID from device.env, and the installed cert is the new one.
        assert post.seen["url"] == "https://renew.example/renew"
        assert result == post.seen["issued"]
        assert (config / "device.crt").read_bytes().decode() == post.seen["issued"]
