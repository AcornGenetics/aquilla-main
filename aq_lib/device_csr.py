"""On-device keypair + CSR generation for Sentri enrollment (issue #239).

A Sentri generates its own keypair on-device and a CSR whose Subject CN is its
Device ID (the Pi hardware serial). The private key never leaves the Pi. The CSR
is later submitted to acorn-ca ``POST /enroll`` (operator-mediated, #240).
"""
import os
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from aq_lib.device_id import read_rpi_serial


def enrollment_device_id(cpuinfo_path: str = "/proc/cpuinfo") -> str:
    """The Device ID to enroll under: the Pi hardware serial.

    This is deliberately the serial, not the hostname — the cert CN must equal
    what the platform treats as the Device ID (CONTEXT.md). There is no hostname
    fallback: a device with no stable serial must not silently enroll under a
    mutable identity.
    """
    serial = read_rpi_serial(cpuinfo_path)
    if not serial:
        raise RuntimeError(
            f"no Raspberry Pi hardware serial in {cpuinfo_path}; "
            "cannot derive a stable Device ID for enrollment"
        )
    return serial


def generate_device_csr(device_id: str) -> tuple[bytes, bytes]:
    """Generate a fresh device keypair and a CSR with Subject ``CN=device_id``.

    Returns ``(private_key_pem, csr_pem)``.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    csr = x509.CertificateSigningRequestBuilder().subject_name(
        x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, device_id)])
    ).sign(key, hashes.SHA256())

    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    csr_pem = csr.public_bytes(serialization.Encoding.PEM)
    return key_pem, csr_pem


KEY_FILENAME = "device.key"
CSR_FILENAME = "device.csr"


def write_device_csr(out_dir: str, cpuinfo_path: str = "/proc/cpuinfo") -> str:
    """Generate the device keypair + CSR on-device and write them to ``out_dir``.

    Resolves the Device ID from the Pi serial, writes the private key
    owner-only (``0600``) and the CSR alongside it, and returns the Device ID
    so the caller (the enroll step, #240) can submit the CSR under that identity.
    """
    device_id = enrollment_device_id(cpuinfo_path)
    key_pem, csr_pem = generate_device_csr(device_id)

    key_path = os.path.join(out_dir, KEY_FILENAME)
    csr_path = os.path.join(out_dir, CSR_FILENAME)
    # Create the key file owner-only from the start — never world-readable, even
    # for the instant between write and chmod.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key_pem)
    with open(csr_path, "wb") as f:
        f.write(csr_pem)
    return device_id


if __name__ == "__main__":  # pragma: no cover - on-device entrypoint
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    print(write_device_csr(out))
