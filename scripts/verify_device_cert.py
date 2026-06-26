#!/usr/bin/env python3
"""Device-side certificate verification (#242).

Runs ON the Pi. Presents the installed Device Certificate over mTLS to acorn-ca
``/renew`` and reports whether it authenticates. Exits 0 (PASS) or non-zero
(FAIL). No AWS credentials are needed — the certificate is the credential.

    python scripts/verify_device_cert.py \
        --renew-endpoint https://renew.cloud.acorngenetics.com/renew

Cert/key paths and the Device ID default to the values enrollment wrote into
``device.env`` (#240).
"""
import argparse
import os
import sys

from aq_lib.verify import VerificationError, verify_renew


def main(argv=None):
    p = argparse.ArgumentParser(description="Verify the Device Certificate over mTLS.")
    p.add_argument("--renew-endpoint", default=os.getenv("AQ_RENEW_ENDPOINT"))
    p.add_argument("--cert", default=os.getenv("AQ_SYNC_CLIENT_CERT"))
    p.add_argument("--key", default=os.getenv("AQ_SYNC_CLIENT_KEY"))
    p.add_argument(
        "--device-id",
        default=os.getenv("AQ_SYNC_DEVICE_ID") or os.getenv("DEVICE_ID"),
    )
    args = p.parse_args(argv)

    missing = [
        name
        for name, value in [
            ("--renew-endpoint", args.renew_endpoint),
            ("--cert", args.cert),
            ("--key", args.key),
            ("--device-id", args.device_id),
        ]
        if not value
    ]
    if missing:
        sys.exit(f"missing required value(s): {', '.join(missing)}")

    try:
        verify_renew(
            args.renew_endpoint,
            cert_path=args.cert, key_path=args.key, device_id=args.device_id,
        )
    except VerificationError as e:
        sys.exit(f"FAIL: {e}")

    print("PASS: Device Certificate authenticated over mTLS to /renew")


if __name__ == "__main__":
    main()
