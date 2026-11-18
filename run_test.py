#!/usr/bin/env python3
"""Run E2E test and capture full traceback."""

import sys
import traceback

import pytest

if __name__ == "__main__":
    try:
        result = pytest.main(
            [
                "tests/test_e2e_playwright.py::test_homepage_loads",
                "-v",
                "--tb=long",
                "-s",
                "--capture=no",
                "-x",
            ]
        )
        sys.exit(result)
    except Exception:  # noqa: BLE001 - E2E runner: print traceback and exit
        traceback.print_exc()
        sys.exit(1)
