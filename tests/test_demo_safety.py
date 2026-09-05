import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_demo_rejects_conflicting_database_targets_before_native_actions() -> None:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 required for the Windows demo safety check")
    environment = dict(os.environ)
    environment.update(
        INCIDENT_INTEL_DATABASE_URL="postgresql://synthetic-runtime.invalid/demo",
        INCIDENT_INTEL_TEST_DATABASE_URL="postgresql://synthetic-tests.invalid/tests",
        INCIDENT_INTEL_TOKEN_SECRET="synthetic-test-only-not-a-runtime-secret",
    )
    script = Path(__file__).parents[1] / "scripts" / "demo.ps1"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-File", str(script)], env=environment,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "Database URLs disagree" in result.stderr
