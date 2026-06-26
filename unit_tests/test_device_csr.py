"""
Unit tests for on-device keypair + CSR generation (aq_lib/device_csr.py).

Pure logic, no hardware: a Sentri generates its own keypair and a CSR whose
Subject CN is its Device ID (the Pi hardware serial). Issue #239.
"""
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import pytest

from aq_lib.device_csr import (
    enrollment_device_id,
    generate_device_csr,
    write_device_csr,
)

CPUINFO_WITH_SERIAL = (
    "Hardware\t: BCM2711\n"
    "Serial\t\t: 10000000a6b7d43e\n"
    "Model\t: Raspberry Pi 4 Model B Rev 1.5\n"
)


class TestGenerateDeviceCsr:
    def test_csr_subject_cn_is_the_device_id(self):
        device_id = "10000000a6b7d43e"
        _key_pem, csr_pem = generate_device_csr(device_id)

        csr = x509.load_pem_x509_csr(csr_pem)
        (cn,) = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert cn.value == device_id

    def test_csr_is_signed_by_its_own_key(self):
        # The CSR proves the device holds the private key for the public key it
        # presents — a CA can trust the CSR came from the device it names.
        _key_pem, csr_pem = generate_device_csr("10000000a6b7d43e")

        csr = x509.load_pem_x509_csr(csr_pem)
        assert csr.is_signature_valid is True

    def test_private_key_is_ec_p256_matching_the_csr(self):
        # The returned key is a usable EC P-256 private key, and it is *the* key
        # whose public half the CSR carries — so installing it lets the device
        # use the certificate the CA issues against this CSR.
        key_pem, csr_pem = generate_device_csr("10000000a6b7d43e")

        key = serialization.load_pem_private_key(key_pem, password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        assert isinstance(key.curve, ec.SECP256R1)

        csr = x509.load_pem_x509_csr(csr_pem)
        assert csr.public_key().public_numbers() == key.public_key().public_numbers()


class TestEnrollmentDeviceId:
    def test_is_the_pi_hardware_serial(self, tmp_path):
        # The enrollment identity is the Pi serial (CONTEXT.md), not the
        # hostname — the cert CN must equal what the platform treats as Device ID.
        f = tmp_path / "cpuinfo"
        f.write_text(CPUINFO_WITH_SERIAL)
        assert enrollment_device_id(str(f)) == "10000000a6b7d43e"

    def test_raises_rather_than_falling_back_to_hostname(self, tmp_path):
        # No serial → fail loudly. Never enroll under a mutable identity (the old
        # hostname-derived DEVICE_ID), which would mint a cert under the wrong CN.
        with pytest.raises(RuntimeError):
            enrollment_device_id(str(tmp_path / "nonexistent"))


class TestWriteDeviceCsr:
    def test_writes_owner_only_key_and_csr_named_for_the_serial(self, tmp_path):
        cpuinfo = tmp_path / "cpuinfo"
        cpuinfo.write_text(CPUINFO_WITH_SERIAL)
        out = tmp_path / "config"
        out.mkdir()

        device_id = write_device_csr(str(out), cpuinfo_path=str(cpuinfo))

        # Caller (the enroll step, #240) gets the Device ID back.
        assert device_id == "10000000a6b7d43e"

        key = out / "device.key"
        csr_file = out / "device.csr"
        assert key.exists() and csr_file.exists()
        # The private key is written owner-only — never world-readable on the Pi.
        assert (key.stat().st_mode & 0o777) == 0o600
        # The CSR carries the Pi serial as its CN.
        csr = x509.load_pem_x509_csr(csr_file.read_bytes())
        (cn,) = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert cn.value == "10000000a6b7d43e"
