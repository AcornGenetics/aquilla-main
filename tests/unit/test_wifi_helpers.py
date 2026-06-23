"""
Unit tests for WiFi helper functions in kiosk_control.py and apply_wifi.py.

No hardware required — all subprocess calls are mocked.

Run with:
    pytest tests/unit/test_wifi_helpers.py -v
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

# Make scripts importable without installing them
SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR / "kiosk-control"))
sys.path.insert(0, str(SCRIPTS_DIR))

import kiosk_control as kc
import apply_wifi


# ===========================================================================
# kiosk_control — _wifi_status
# ===========================================================================

def _nmcli_result(returncode, stdout, stderr=""):
    return (returncode, stdout, stderr)


class TestWifiStatus:
    def test_connected_parses_ssid_and_signal(self):
        output = "yes:HomeNetwork:80:WPA2"
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, output)):
            result = kc._wifi_status()
        assert result["connected"] is True
        assert result["ssid"] == "HomeNetwork"
        assert result["signal"] == 80

    def test_not_connected_returns_false(self):
        output = "no:OtherNet:60:WPA2"
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, output)):
            result = kc._wifi_status()
        assert result["connected"] is False

    def test_empty_output_returns_false(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")):
            result = kc._wifi_status()
        assert result["connected"] is False

    def test_nmcli_failure_returns_error(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(1, "", "device not found")):
            result = kc._wifi_status()
        assert result["connected"] is False
        assert "error" in result

    def test_missing_signal_field_handled(self):
        output = "yes:HomeNetwork"
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, output)):
            result = kc._wifi_status()
        assert result["connected"] is True
        assert result["signal"] is None


# ===========================================================================
# kiosk_control — _wifi_scan
# ===========================================================================

class TestWifiScan:
    def _patch_nmcli(self, scan_return, list_return):
        """Return a side_effect list: first call is rescan, second is list."""
        return [scan_return, list_return]

    def test_returns_sorted_networks(self):
        list_out = "LowSignal:20:WPA2:*\nHighSignal:90:WPA2:\nMidSignal:50:--:"
        side_effects = [
            _nmcli_result(0, ""),        # rescan
            _nmcli_result(0, list_out),  # list
            _nmcli_result(0, ""),        # connection show
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        ssids = [n["ssid"] for n in result]
        assert ssids[0] == "HighSignal"
        assert ssids[-1] == "LowSignal"

    def test_in_use_network_flagged(self):
        list_out = "ActiveNet:70:WPA2:*\nOtherNet:50:WPA2:"
        side_effects = [
            _nmcli_result(0, ""),
            _nmcli_result(0, list_out),
            _nmcli_result(0, ""),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        active = next(n for n in result if n["ssid"] == "ActiveNet")
        other = next(n for n in result if n["ssid"] == "OtherNet")
        assert active["in_use"] is True
        assert other["in_use"] is False

    def test_open_network_secured_false(self):
        list_out = "OpenNet:60:--:"
        side_effects = [
            _nmcli_result(0, ""),
            _nmcli_result(0, list_out),
            _nmcli_result(0, ""),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        assert result[0]["secured"] is False

    def test_duplicate_ssids_deduplicated(self):
        list_out = "DupNet:60:WPA2:\nDupNet:55:WPA2:"
        side_effects = [
            _nmcli_result(0, ""),
            _nmcli_result(0, list_out),
            _nmcli_result(0, ""),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        assert len(result) == 1

    def test_empty_output_returns_empty_list(self):
        side_effects = [
            _nmcli_result(0, ""),
            _nmcli_result(0, ""),
            _nmcli_result(0, ""),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        assert result == []

    def test_saved_field_true_for_known_profile(self):
        list_out = "StaleNet:60:WPA2:\nFreshNet:50:WPA2:"
        saved_out = "StaleNet\nAcorn Genetics"
        side_effects = [
            _nmcli_result(0, ""),
            _nmcli_result(0, list_out),
            _nmcli_result(0, saved_out),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        stale = next(n for n in result if n["ssid"] == "StaleNet")
        fresh = next(n for n in result if n["ssid"] == "FreshNet")
        assert stale["saved"] is True
        assert fresh["saved"] is False


# ===========================================================================
# kiosk_control — _delete_profiles_for_ssid
# ===========================================================================

class TestDeleteProfilesForSsid:
    def test_deletes_profile_whose_ssid_matches(self):
        side_effects = [
            _nmcli_result(0, "HomeNet:802-11-wireless"),  # NAME,TYPE list
            _nmcli_result(0, "HomeNet"),                  # ssid for HomeNet → matches
            _nmcli_result(0, ""),                         # delete
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._delete_profiles_for_ssid("HomeNet")
        calls = [c[0] for c in mock_nmcli.call_args_list]
        assert any(c[:2] == ("connection", "delete") for c in calls)

    def test_does_not_delete_non_matching_profile(self):
        side_effects = [
            _nmcli_result(0, "OfficeNet:802-11-wireless"),
            _nmcli_result(0, "OfficeNet"),  # ssid → does not match HomeNet
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._delete_profiles_for_ssid("HomeNet")
        calls = [c[0] for c in mock_nmcli.call_args_list]
        assert not any(c[:2] == ("connection", "delete") for c in calls)

    def test_deletes_multiple_profiles_for_same_ssid(self):
        # iPhone hotspots can create several numbered profiles for the same SSID.
        side_effects = [
            _nmcli_result(0, "iPhone:802-11-wireless\niPhone (2):802-11-wireless"),
            _nmcli_result(0, "HomeNet"),  # ssid for "iPhone" → matches
            _nmcli_result(0, ""),         # delete "iPhone"
            _nmcli_result(0, "HomeNet"),  # ssid for "iPhone (2)" → also matches
            _nmcli_result(0, ""),         # delete "iPhone (2)"
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._delete_profiles_for_ssid("HomeNet")
        delete_calls = [c[0] for c in mock_nmcli.call_args_list if c[0][:2] == ("connection", "delete")]
        assert len(delete_calls) == 2

    def test_skips_non_wireless_connections(self):
        side_effects = [
            _nmcli_result(0, "Wired:802-3-ethernet\nVPN:vpn"),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._delete_profiles_for_ssid("HomeNet")
        # Only the list call — no ssid checks, no deletes
        assert mock_nmcli.call_count == 1

    def test_empty_profile_list_is_a_noop(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")) as mock_nmcli:
            kc._delete_profiles_for_ssid("HomeNet")
        assert mock_nmcli.call_count == 1  # only the NAME,TYPE list call


# ===========================================================================
# kiosk_control — _wifi_connect
# ===========================================================================

class TestWifiConnect:
    def _no_profiles(self):
        """Side-effect list when there are no saved profiles."""
        return [_nmcli_result(0, "")]  # NAME,TYPE list → empty

    def test_connect_with_password_creates_explicit_wpa_psk_profile(self):
        side_effects = self._no_profiles() + [
            _nmcli_result(0, ""),  # connection add
            _nmcli_result(0, ""),  # connection up
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._wifi_connect("HomeNet", "secret")
        calls = [c[0] for c in mock_nmcli.call_args_list]
        add_call = next(c for c in calls if c[:2] == ("connection", "add"))
        assert "wifi-sec.key-mgmt" in add_call
        assert "wpa-psk" in add_call
        assert "wifi-sec.psk" in add_call
        assert "secret" in add_call

    def test_connect_with_password_does_not_use_device_wifi_connect(self):
        side_effects = self._no_profiles() + [
            _nmcli_result(0, ""),  # connection add
            _nmcli_result(0, ""),  # connection up
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._wifi_connect("HomeNet", "secret")
        calls = [c[0] for c in mock_nmcli.call_args_list]
        assert not any(c[:3] == ("device", "wifi", "connect") for c in calls)

    def test_connect_without_password_uses_device_wifi_connect(self):
        side_effects = self._no_profiles() + [
            _nmcli_result(0, ""),  # device wifi connect
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            kc._wifi_connect("OpenNet", "")
        calls = [c[0] for c in mock_nmcli.call_args_list]
        assert any(c[:3] == ("device", "wifi", "connect") for c in calls)

    def test_returns_ok_true_on_success(self):
        side_effects = self._no_profiles() + [
            _nmcli_result(0, ""),  # connection add
            _nmcli_result(0, ""),  # connection up
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects):
            result = kc._wifi_connect("HomeNet", "secret")
        assert result["ok"] is True
        assert result["error"] is None

    def test_returns_ok_false_when_connection_add_fails(self):
        side_effects = self._no_profiles() + [
            _nmcli_result(1, "", "Error: failed to add connection"),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects):
            result = kc._wifi_connect("HomeNet", "wrongpass")
        assert result["ok"] is False
        assert "failed to add" in result["error"]

    def test_returns_ok_false_when_connection_up_fails(self):
        side_effects = self._no_profiles() + [
            _nmcli_result(0, ""),                              # connection add OK
            _nmcli_result(1, "", "Secrets were required"),     # connection up fails
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects):
            result = kc._wifi_connect("HomeNet", "wrongpass")
        assert result["ok"] is False
        assert "Secrets were required" in result["error"]

    def test_purges_existing_stale_profile_before_connecting(self):
        side_effects = [
            _nmcli_result(0, "HomeNet:802-11-wireless"),  # list profiles
            _nmcli_result(0, "HomeNet"),                  # ssid check → match
            _nmcli_result(0, ""),                         # delete stale profile
            _nmcli_result(0, ""),                         # connection add
            _nmcli_result(0, ""),                         # connection up
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            result = kc._wifi_connect("HomeNet", "newpass")
        assert result["ok"] is True
        calls = [c[0] for c in mock_nmcli.call_args_list]
        assert any(c[:2] == ("connection", "delete") for c in calls)


# ===========================================================================
# kiosk_control — _wifi_forget
# ===========================================================================

class TestWifiForget:
    def test_forget_deletes_all_profiles_matching_ssid(self):
        side_effects = [
            _nmcli_result(0, "HomeNet:802-11-wireless"),
            _nmcli_result(0, "HomeNet"),  # ssid match
            _nmcli_result(0, ""),         # delete
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects) as mock_nmcli:
            result = kc._wifi_forget("HomeNet")
        assert result["ok"] is True
        calls = [c[0] for c in mock_nmcli.call_args_list]
        assert any(c[:2] == ("connection", "delete") for c in calls)

    def test_returns_ok_true_when_no_profile_exists(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")):
            result = kc._wifi_forget("NonExistent")
        assert result["ok"] is True
        assert result["error"] is None

    def test_returns_ok_true_on_success(self):
        side_effects = [
            _nmcli_result(0, "HomeNet:802-11-wireless"),
            _nmcli_result(0, "HomeNet"),
            _nmcli_result(0, ""),
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects):
            result = kc._wifi_forget("HomeNet")
        assert result["ok"] is True


# ===========================================================================
# apply_wifi — _strip_network_block
# ===========================================================================

class TestStripNetworkBlock:
    def test_removes_matching_block(self):
        lines = [
            "country=US",
            "network={",
            '    ssid="HomeNet"',
            '    psk="secret"',
            "    key_mgmt=WPA-PSK",
            "}",
        ]
        result = apply_wifi._strip_network_block(lines, "HomeNet")
        assert "network={" not in result
        assert '    ssid="HomeNet"' not in result

    def test_keeps_non_matching_block(self):
        lines = [
            "network={",
            '    ssid="OtherNet"',
            '    psk="pass"',
            "    key_mgmt=WPA-PSK",
            "}",
        ]
        result = apply_wifi._strip_network_block(lines, "HomeNet")
        assert '    ssid="OtherNet"' in result

    def test_removes_only_matching_block_when_multiple(self):
        lines = [
            "network={",
            '    ssid="Remove"',
            '    psk="a"',
            "}",
            "network={",
            '    ssid="Keep"',
            '    psk="b"',
            "}",
        ]
        result = apply_wifi._strip_network_block(lines, "Remove")
        assert '    ssid="Remove"' not in result
        assert '    ssid="Keep"' in result


# ===========================================================================
# apply_wifi — _ensure_header
# ===========================================================================

class TestEnsureHeader:
    def test_adds_header_to_empty_file(self):
        result = apply_wifi._ensure_header([], "US")
        assert any("country=US" in l for l in result)
        assert any("ctrl_interface" in l for l in result)

    def test_does_not_add_header_when_country_present(self):
        lines = ["country=GB", "update_config=1"]
        result = apply_wifi._ensure_header(lines, "US")
        country_lines = [l for l in result if l.strip().startswith("country=")]
        assert len(country_lines) == 1  # not duplicated
        assert "country=GB" in country_lines[0]


# ===========================================================================
# apply_wifi — apply_wifi_config (integration of helpers)
# ===========================================================================

class TestApplyWifiConfig:
    def test_writes_network_block_and_calls_wpa_cli(self, tmp_path):
        wifi_json = tmp_path / "wifi.json"
        wifi_json.write_text(json.dumps({"ssid": "TestNet", "psk": "testpass", "country": "US"}))
        wpa_conf = tmp_path / "wpa_supplicant.conf"

        with patch.object(apply_wifi, "CONFIG_PATH", wifi_json), \
             patch.object(apply_wifi, "WPA_SUPPLICANT_PATH", wpa_conf), \
             patch("apply_wifi.shutil.which", return_value=None), \
             patch("apply_wifi.subprocess.run") as mock_run:
            apply_wifi.apply_wifi_config()

        content = wpa_conf.read_text()
        assert 'ssid="TestNet"' in content
        assert 'psk="testpass"' in content
        assert "key_mgmt=WPA-PSK" in content
        mock_run.assert_called_once()
        assert "wpa_cli" in mock_run.call_args[0][0]

    def test_raises_if_config_missing(self, tmp_path):
        with patch.object(apply_wifi, "CONFIG_PATH", tmp_path / "missing.json"):
            with pytest.raises(FileNotFoundError):
                apply_wifi.apply_wifi_config()

    def test_raises_if_ssid_empty(self, tmp_path):
        wifi_json = tmp_path / "wifi.json"
        wifi_json.write_text(json.dumps({"ssid": "", "psk": "pass"}))
        with patch.object(apply_wifi, "CONFIG_PATH", wifi_json):
            with pytest.raises(ValueError):
                apply_wifi.apply_wifi_config()

    def test_raises_if_psk_empty(self, tmp_path):
        wifi_json = tmp_path / "wifi.json"
        wifi_json.write_text(json.dumps({"ssid": "Net", "psk": ""}))
        with patch.object(apply_wifi, "CONFIG_PATH", wifi_json):
            with pytest.raises(ValueError):
                apply_wifi.apply_wifi_config()

    def test_replaces_existing_network_block(self, tmp_path):
        wifi_json = tmp_path / "wifi.json"
        wifi_json.write_text(json.dumps({"ssid": "TestNet", "psk": "newpass"}))
        wpa_conf = tmp_path / "wpa_supplicant.conf"
        wpa_conf.write_text(
            'country=US\nnetwork={\n    ssid="TestNet"\n    psk="oldpass"\n    key_mgmt=WPA-PSK\n}\n'
        )

        with patch.object(apply_wifi, "CONFIG_PATH", wifi_json), \
             patch.object(apply_wifi, "WPA_SUPPLICANT_PATH", wpa_conf), \
             patch("apply_wifi.shutil.which", return_value=None), \
             patch("apply_wifi.subprocess.run"):
            apply_wifi.apply_wifi_config()

        content = wpa_conf.read_text()
        assert content.count('ssid="TestNet"') == 1
        assert 'psk="newpass"' in content
        assert 'psk="oldpass"' not in content

    def test_uses_nmcli_when_networkmanager_available(self, tmp_path):
        wifi_json = tmp_path / "wifi.json"
        wifi_json.write_text(json.dumps({"ssid": "TestNet", "psk": "testpass"}))

        def fake_run(cmd, **kwargs):
            mock = MagicMock()
            mock.returncode = 0
            # Profile list returns empty → no stale profiles to delete
            mock.stdout = ""
            return mock

        with patch.object(apply_wifi, "CONFIG_PATH", wifi_json), \
             patch("apply_wifi.shutil.which", return_value="/usr/bin/nmcli"), \
             patch("apply_wifi.subprocess.run", side_effect=fake_run) as mock_run:
            apply_wifi.apply_wifi_config()

        mock_run.assert_any_call(
            ["nmcli", "general", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        mock_run.assert_any_call(
            [
                "nmcli", "connection", "add",
                "type", "wifi",
                "con-name", "TestNet",
                "ssid", "TestNet",
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", "testpass",
            ],
            check=True,
        )
        mock_run.assert_any_call(["nmcli", "connection", "up", "TestNet"], check=True)
