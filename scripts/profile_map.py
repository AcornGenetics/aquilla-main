"""
profile_map.py — read-only CLI showing which profiles each device sees.

Usage:
    python scripts/profile_map.py
    python scripts/profile_map.py --device sn02
    python scripts/profile_map.py --profile ABBA_ramp1.75_EA30.json
    python scripts/profile_map.py --group classic
"""
import argparse
import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config_files"
DEVICE_PROFILES_PATH = CONFIG_DIR / "device_profiles.json"
PROFILE_GROUPS_PATH = CONFIG_DIR / "profile_groups.json"

SEP = "─" * 64


def load_configs():
    device_profiles = json.loads(DEVICE_PROFILES_PATH.read_text())
    profile_groups = json.loads(PROFILE_GROUPS_PATH.read_text())
    return device_profiles, profile_groups


def resolve_profiles_for_device(device_entry: dict, profile_groups: dict) -> list[str] | None:
    group_name = device_entry.get("profile_group")
    group_value = profile_groups.get(group_name)
    if group_value is None:
        return None
    result = list(group_value)
    result.extend(device_entry.get("extra_profiles", []))
    return result


def print_device_row(device: str, device_entry: dict, profile_groups: dict):
    group_name = device_entry.get("profile_group", "?")
    profiles = resolve_profiles_for_device(device_entry, profile_groups)
    extras = device_entry.get("extra_profiles", [])

    if profiles is None:
        print(f"{device:<10}{group_name:<20}(all profiles)")
        return

    group_profiles = [p for p in profiles if p not in extras]
    first = True
    for p in group_profiles:
        if first:
            print(f"{device:<10}{group_name:<20}{p}")
            first = False
        else:
            print(f"{'':10}{'':20}{p}")
    if extras:
        first_extra = True
        for p in extras:
            if first_extra:
                print(f"{'':10}{'+ extra':<20}{p}")
                first_extra = False
            else:
                print(f"{'':10}{'':20}{p}")
    if not profiles:
        print(f"{device:<10}{group_name:<20}(none)")


def main():
    parser = argparse.ArgumentParser(description="Show per-device profile assignments")
    parser.add_argument("--device", help="Show only one device")
    parser.add_argument("--profile", help="Show all devices that have a given profile")
    parser.add_argument("--group", help="Show all devices assigned to a group")
    args = parser.parse_args()

    device_profiles, profile_groups = load_configs()

    print()
    print(f"{'Device':<10}{'Group':<20}{'Profiles'}")
    print(SEP)

    for device, entry in sorted(device_profiles.items()):
        if args.device and device != args.device:
            continue
        if args.group and entry.get("profile_group") != args.group:
            continue
        if args.profile:
            profiles = resolve_profiles_for_device(entry, profile_groups)
            if profiles is not None and args.profile not in profiles:
                continue
            if profiles is None:
                pass
        print_device_row(device, entry, profile_groups)

    print()


if __name__ == "__main__":
    main()
