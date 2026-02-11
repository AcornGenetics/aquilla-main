#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path

from config import get_src_basedir


def run_command(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT)


def list_services() -> list[str]:
    output = run_command(
        [
            "systemctl",
            "list-units",
            "--type=service",
            "--state=running",
            "--no-legend",
            "--no-pager",
        ]
    )
    services = []
    for line in output.splitlines():
        parts = line.split()
        if parts:
            services.append(parts[0])
    return services


def read_service(service: str) -> list[str]:
    output = run_command(["systemctl", "cat", service, "--no-pager"])
    return output.splitlines()


def should_check_line(line: str) -> bool:
    return line.startswith("WorkingDirectory=") or line.startswith("ExecStart=") or line.startswith(
        "Environment="
    )


def check_service(service: str, base_dir: str) -> list[str]:
    mismatches = []
    for line in read_service(service):
        if not should_check_line(line):
            continue
        if "AQ_SRC_BASEDIR=" in line and base_dir not in line:
            mismatches.append(f"{service}: {line}")
            continue
        if "/home/pi/" in line and base_dir not in line:
            mismatches.append(f"{service}: {line}")
    return mismatches


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check systemd service paths against AQ_SRC_BASEDIR."
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Override base dir (default: AQ_SRC_BASEDIR or config.py).",
    )
    parser.add_argument(
        "--pattern",
        default=None,
        help="Only check services containing this substring.",
    )
    args = parser.parse_args()

    base_dir = args.base_dir or get_src_basedir()
    base_dir = str(Path(base_dir).expanduser())
    services = list_services()
    if args.pattern:
        services = [service for service in services if args.pattern in service]

    all_mismatches = []
    for service in services:
        all_mismatches.extend(check_service(service, base_dir))

    print(f"AQ_SRC_BASEDIR: {base_dir}")
    if all_mismatches:
        print("Mismatches:")
        for mismatch in all_mismatches:
            print(f"- {mismatch}")
    else:
        print("All checked services match base dir.")


if __name__ == "__main__":
    main()
