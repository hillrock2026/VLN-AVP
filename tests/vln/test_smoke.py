"""Phase-1 smoke tests: the skeleton package imports cleanly."""

import vln


def test_package_has_version() -> None:
    assert vln.__version__ == "0.0.0"


def test_no_public_api_yet() -> None:
    # Phase 1 exposes no public API; this guards against accidental additions.
    assert vln.__all__ == []
