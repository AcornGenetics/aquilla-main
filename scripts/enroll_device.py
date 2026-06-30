#!/usr/bin/env python3
"""Operator-side device enrollment over Tailscale SSH (#240).

Run this on the OPERATOR'S machine, where AWS credentials are present — never on
the Pi. It pulls the Sentri's CSR off the Pi, enrols it against acorn-ca
``/enroll`` (SigV4-signed with the operator's AWS identity), then installs the
issued Device Certificate (``0600``) and updates ``device.env`` on the Pi over
SSH. AWS credentials never touch the Pi.

    python scripts/enroll_device.py --pi sn04 \
        --endpoint https://1x9561i626.execute-api.us-east-2.amazonaws.com/enroll \
        --region us-east-2

The ``--endpoint`` is the acorn-ca EnrollApi URL for the target environment (the
example above is **prod**). Find the current one with:

    aws apigatewayv2 get-apis \
      --query "Items[?Name=='EnrollApi'].ApiEndpoint" --output text   # append /enroll

The CSR is produced on the Pi during deployment (#239). The Sync client reads
the installed cert/key paths from ``device.env`` (#241).
"""
import argparse
import subprocess
import sys

import botocore.session

from aq_lib.enroll import EnrollmentError, device_env_after_enroll, enroll

CONFIG_DIR = "/opt/aquila/config"
CSR_PATH = f"{CONFIG_DIR}/device.csr"
CERT_PATH = f"{CONFIG_DIR}/device.crt"
KEY_PATH = f"{CONFIG_DIR}/device.key"
ENV_PATH = f"{CONFIG_DIR}/device.env"


def _ssh_read(pi, path):
    # /opt/aquila/config is root-owned (deployment2.sh runs under sudo), and
    # device.env is 0600 root — so read via sudo. The Pi user has passwordless
    # sudo; AWS creds still never touch the Pi (this only runs `cat` there).
    return subprocess.run(
        ["ssh", pi, "sudo", "cat", path], check=True, capture_output=True, text=True
    ).stdout


def _ssh_write(pi, path, content, mode="600"):
    # Write into the root-owned config dir as root via `sudo tee`. `umask 077`
    # (inherited by tee) keeps the file non-world-readable even momentarily;
    # `sudo chmod` pins the final mode. The file ends up root-owned, matching the
    # rest of /opt/aquila/config.
    subprocess.run(
        ["ssh", pi, f"umask 077 && sudo tee {path} >/dev/null && sudo chmod {mode} {path}"],
        input=content, check=True, capture_output=True, text=True,
    )


def main(argv=None):
    p = argparse.ArgumentParser(description="Enrol a Sentri's Device Certificate.")
    p.add_argument("--pi", required=True, help="Tailscale host/IP of the Sentri")
    p.add_argument("--endpoint", required=True, help="acorn-ca /enroll URL")
    p.add_argument("--region", default="us-east-2")
    args = p.parse_args(argv)

    creds = botocore.session.get_session().get_credentials()
    if creds is None:
        sys.exit(
            "no AWS credentials on this machine — enrolment must run where the "
            "operator is authenticated (creds never go on the Pi)"
        )

    csr_pem = _ssh_read(args.pi, CSR_PATH)
    try:
        cert_pem = enroll(
            csr_pem, args.endpoint,
            region=args.region, credentials=creds.get_frozen_credentials(),
        )
    except EnrollmentError as e:
        sys.exit(f"enrolment failed: {e}")

    _ssh_write(args.pi, CERT_PATH, cert_pem)
    new_env = device_env_after_enroll(
        _ssh_read(args.pi, ENV_PATH), cert_path=CERT_PATH, key_path=KEY_PATH
    )
    _ssh_write(args.pi, ENV_PATH, new_env)

    print(f"enrolled {args.pi}: certificate installed at {CERT_PATH}")


if __name__ == "__main__":
    main()
