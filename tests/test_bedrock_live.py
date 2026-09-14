import os

import pytest

from rivalmap.vertical_slice import build_bedrock_vertical_slice


@pytest.mark.live
def test_live_bedrock_exa_vertical_slice():
    if os.getenv("RIVALMAP_RUN_LIVE_TESTS") != "1":
        pytest.skip("set RIVALMAP_RUN_LIVE_TESTS=1 to enable live Bedrock/Exa testing")
    runner = build_bedrock_vertical_slice()
    events = list(
        runner.stream(
            "AI interview coaching platform",
            target_user="job seekers",
            problem="practice interviews and receive feedback",
        )
    )
    assert any(event.visualization_delta is not None for event in events)
