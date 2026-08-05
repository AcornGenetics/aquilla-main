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

from aq_lib.renew import (
    ROTATION_MARKER,
    RenewalError,
    recover_if_broken,
    renew_device_cert,
    renewal_due,
    run_renewal,
)

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


def make_matching_pair(now: dt.datetime) -> tuple[bytes, bytes]:
    """A genuinely consistent (cert, key) pair, in-date at ``now`` — the cert is
    signed for the returned key's public key (unlike make_cert_pem, whose key is
    internal and discarded)."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, DEVICE_ID)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=13))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return cert.public_bytes(serialization.Encoding.PEM), key_pem


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


class TestRenewalRollback:
    """A rotation the device can't verify must NOT brick it (am#405).

    Before overwriting, the renewer backs up the current (working) pair. After
    installing the new one it verifies it; if verification fails it rolls back to
    the previous cert/key — which is still valid (renewal fires at ~2/3 of life) —
    so a bad rotation is survivable instead of needing offline re-enrollment.
    """

    def test_rolls_back_to_the_previous_pair_when_verification_fails(self, tmp_path):
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now), key_pem=make_keypair_pem())
        before_crt = (config / "device.crt").read_bytes()
        before_key = (config / "device.key").read_bytes()

        with pytest.raises(RenewalError):
            renew_device_cert(
                RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
                now=now, http_post=issuing_post(now),
                verify=lambda cert_path, key_path, now: False,
            )

        # The installed pair is the ORIGINAL one — the unverifiable cert was not kept.
        assert (config / "device.crt").read_bytes() == before_crt
        assert (config / "device.key").read_bytes() == before_key

    def test_clears_the_backup_after_a_verified_renewal(self, tmp_path):
        # Once the new cert is confirmed good, the .bak copies are dropped — no
        # stale backup lingers to confuse a later crash-recovery check.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))

        renew_device_cert(
            RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
            now=now, http_post=issuing_post(now),  # default verify passes
        )

        assert not (config / "device.crt.bak").exists()
        assert not (config / "device.key.bak").exists()

    def test_recover_if_broken_restores_a_mismatched_pair_from_backup(self, tmp_path):
        # Crash mid-install: installed = new key + old cert (they don't match); the
        # .bak still holds the previous good pair. Recovery restores the good pair.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        good_cert, good_key = make_matching_pair(now)
        write_config(config, good_cert, key_pem=good_key)
        (config / "device.crt.bak").write_bytes(good_cert)
        (config / "device.key.bak").write_bytes(good_key)
        # Clobber the installed key with a different one → mismatched (crash state).
        (config / "device.key").write_bytes(make_keypair_pem())

        recover_if_broken(str(config), now=now)

        assert (config / "device.crt").read_bytes() == good_cert
        assert (config / "device.key").read_bytes() == good_key
        assert not (config / "device.key.bak").exists()

    def test_recover_if_broken_leaves_a_valid_pair_untouched(self, tmp_path):
        # A healthy installed pair must never be clobbered by a stale backup.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        good_cert, good_key = make_matching_pair(now)
        write_config(config, good_cert, key_pem=good_key)  # matching, in-date
        (config / "device.crt.bak").write_bytes(b"STALE")
        (config / "device.key.bak").write_bytes(b"STALE")

        recover_if_broken(str(config), now=now)

        assert (config / "device.crt").read_bytes() == good_cert  # untouched


class TestGreengrassReconnectMarker:
    """After a rotation, the container must signal the host to reconnect Greengrass.

    Greengrass reads device.crt once at startup and holds a long-lived MQTT
    connection, so it won't pick up a rotated cert until greengrass.service
    restarts. The renewal runs in a container and can't touch the host's systemd,
    so on a successful rotation it drops a marker in the (bind-mounted) config dir;
    a host-side hook sees it and bounces Greengrass. No rotation => no marker, so a
    healthy connection is never bounced needlessly.
    """

    def test_rotation_drops_the_reconnect_marker(self, tmp_path):
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))
        post = issuing_post(now)

        renew_device_cert(
            RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
            now=now, http_post=post,
        )

        assert (config / ROTATION_MARKER).exists()

    def test_not_due_leaves_no_marker(self, tmp_path):
        # Nothing rotated, so Greengrass's healthy long-lived connection must not be
        # bounced. A daily no-op tick must never leave a marker.
        now = dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        fresh = make_cert_pem(
            not_before=now - dt.timedelta(days=1),
            not_after=now + dt.timedelta(days=13),
        )
        write_config(config, fresh)

        result = renew_device_cert(
            RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
            now=now, http_post=lambda *a, **k: pytest.fail("must not contact /renew"),
        )

        assert result is None
        assert not (config / ROTATION_MARKER).exists()

    def test_failed_renewal_leaves_no_marker(self, tmp_path):
        # Due, but /renew refused: the installed cert is unchanged, so there is
        # nothing new to reconnect with. A marker here would bounce Greengrass back
        # onto the same old cert — pointless and disruptive.
        now = dt.datetime(2026, 7, 11, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, due_cert(now))

        def refusing_post(url, data=None, cert=None):
            return FakeResponse(403, {"error": "Device ID is revoked"})

        with pytest.raises(RenewalError):
            renew_device_cert(
                RENEW_ENDPOINT, config_dir=str(config), device_id=DEVICE_ID,
                now=now, http_post=refusing_post,
            )

        assert not (config / ROTATION_MARKER).exists()


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

    def test_force_renews_a_cert_that_is_not_yet_due(self, tmp_path):
        # Testing/ops override: with renew_at=1.0 (what --force maps to) a cert
        # nowhere near expiry is renewed anyway, so a renewal can be triggered on
        # demand instead of waiting until it naturally ages.
        now = dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        fresh = make_cert_pem(
            not_before=now - dt.timedelta(days=1),
            not_after=now + dt.timedelta(days=13),   # ~13/14 left: normally NOT due
        )
        write_config(config, fresh)
        (config / "device.env").write_text(
            f"DEVICE_ID={DEVICE_ID}\nAQ_RENEW_ENDPOINT=https://renew.example/renew\n"
        )
        post = issuing_post(now)

        result = run_renewal(str(config), now=now, http_post=post, renew_at=1.0)

        assert result == post.seen["issued"]
        assert (config / "device.crt").read_bytes().decode() == post.seen["issued"]

    def test_reads_renew_at_override_from_device_env(self, tmp_path):
        # AQ_RENEW_AT in device.env tunes the threshold without a code change;
        # 1.0 makes every run due (the env equivalent of --force).
        now = dt.datetime(2026, 7, 2, tzinfo=dt.timezone.utc)
        config = tmp_path / "config"
        write_config(config, make_cert_pem(
            not_before=now - dt.timedelta(days=1),
            not_after=now + dt.timedelta(days=13),
        ))
        (config / "device.env").write_text(
            f"DEVICE_ID={DEVICE_ID}\n"
            "AQ_RENEW_ENDPOINT=https://renew.example/renew\n"
            "AQ_RENEW_AT=1.0\n"
        )
        post = issuing_post(now)

        result = run_renewal(str(config), now=now, http_post=post)

        assert result == post.seen["issued"]
