"""Contract test: the app version is served from the single config source.

config_files/version.json is the one place the version lives; /version reflects
it (and the Settings/Help footer reads /version). Asserting the endpoint mirrors
the file keeps this non-brittle across version bumps.
"""
import json
import pathlib


def test_version_endpoint_mirrors_the_config_file(client):
    expected = json.loads(pathlib.Path("config_files/version.json").read_text())["app_version"]
    body = client.get("/version").json()
    assert body["version"] == expected
