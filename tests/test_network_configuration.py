from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
UPDATER_ROOT = REPOSITORY_ROOT / "official-source-updater"
sys.path.insert(0, str(UPDATER_ROOT))

import updater


ACTIVE_NETWORK_FILES = (
    REPOSITORY_ROOT / "official-source-updater" / "run.ps1",
    REPOSITORY_ROOT / "tools" / "fetch_npc_decision_order_evidence.ps1",
    REPOSITORY_ROOT / "tools" / "npc_decision_order_targeted.py",
)


class NetworkConfigurationTest(unittest.TestCase):
    def test_local_proxy_is_never_hardcoded(self) -> None:
        for path in ACTIVE_NETWORK_FILES:
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertNotRegex(source, r"127\.0\.0\.1:\d{2,5}")

    def test_updater_removes_inherited_proxy_environment(self) -> None:
        inherited = {
            variable_name: "configured-outside-updater"
            for variable_name in updater.PROXY_ENVIRONMENT_VARIABLES
        }
        with patch.dict(os.environ, inherited, clear=False):
            updater.enforce_direct_network()
            for variable_name in updater.PROXY_ENVIRONMENT_VARIABLES:
                self.assertNotIn(variable_name, os.environ)

    def test_runner_has_no_proxy_argument(self) -> None:
        source = (UPDATER_ROOT / "run.ps1").read_text(encoding="utf-8")
        self.assertNotIn("ProxyUrl", source)


if __name__ == "__main__":
    unittest.main()
