"""Intentional failing test for CI blocking demonstration."""


def test_ci_blocks_red_pull_request() -> None:
    """Prove that a red pull request is not mergeable."""
    assert False
