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
        ]
        with patch.object(kc, "_nmcli", side_effect=side_effects), \
             patch("kiosk_control.time") as mock_time:
            mock_time.sleep = MagicMock()
            result = kc._wifi_scan()
        assert result == []


# ===========================================================================
# kiosk_control — _wifi_connect
# ===========================================================================

class TestWifiConnect:
    def test_connect_with_password_calls_correct_args(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")) as mock_nmcli:
            kc._wifi_connect("HomeNet", "secret")
        mock_nmcli.assert_called_once_with(
            "device", "wifi", "connect", "HomeNet", "password", "secret"
        )

    def test_connect_without_password_omits_password_arg(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")) as mock_nmcli:
            kc._wifi_connect("OpenNet", "")
        mock_nmcli.assert_called_once_with(
            "device", "wifi", "connect", "OpenNet"
        )

    def test_returns_ok_true_on_success(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")):
            result = kc._wifi_connect("HomeNet", "secret")
        assert result["ok"] is True
        assert result["error"] is None

    def test_returns_ok_false_on_failure(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(1, "", "Secrets were required")):
            result = kc._wifi_connect("HomeNet", "wrongpass")
        assert result["ok"] is False
        assert "Secrets were required" in result["error"]


# ===========================================================================
# kiosk_control — _wifi_forget
# ===========================================================================

class TestWifiForget:
    def test_forget_calls_connection_delete(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")) as mock_nmcli:
            kc._wifi_forget("HomeNet")
        mock_nmcli.assert_called_once_with("connection", "delete", "HomeNet")

    def test_returns_ok_true_on_success(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(0, "")):
            result = kc._wifi_forget("HomeNet")
        assert result["ok"] is True

    def test_returns_ok_false_when_not_found(self):
        with patch.object(kc, "_nmcli", return_value=_nmcli_result(1, "", "No connection profile found")):
            result = kc._wifi_forget("NonExistent")
        assert result["ok"] is False
        assert "No connection profile found" in result["error"]


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
             patch("apply_wifi.subprocess.run"):
            apply_wifi.apply_wifi_config()

        content = wpa_conf.read_text()
        assert content.count('ssid="TestNet"') == 1
        assert 'psk="newpass"' in content
        assert 'psk="oldpass"' not in content
