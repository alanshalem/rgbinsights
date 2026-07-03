from __future__ import annotations

import pytest
from app.domain.traffic_light import TrafficLight, classify


@pytest.mark.parametrize(
    ("has_outgoing", "has_incoming", "expected"),
    [
        (False, False, TrafficLight.RED),  # no thread at all
        (True, False, TrafficLight.YELLOW),  # we wrote, no reply
        (False, True, TrafficLight.GREEN),  # they wrote (edge: only incoming)
        (True, True, TrafficLight.GREEN),  # two-way — green beats yellow
    ],
)
def test_classify(has_outgoing: bool, has_incoming: bool, expected: TrafficLight) -> None:
    assert classify(has_outgoing, has_incoming) is expected
