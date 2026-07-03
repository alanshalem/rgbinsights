"""Semáforo domain rule. Pure, no external deps, fully testable."""

from __future__ import annotations

from enum import StrEnum


class TrafficLight(StrEnum):
    """DM conversation state for a user."""

    RED = "red"  # sin interacción por DM (incluye "sin hilo")
    YELLOW = "yellow"  # le escribimos, no contestó
    GREEN = "green"  # nos contestó / ida y vuelta


def classify(has_outgoing: bool, has_incoming: bool) -> TrafficLight:
    """Derive the traffic light from DM direction flags.

    GREEN wins over YELLOW: any incoming message means a real two-way
    interaction, regardless of whether we also wrote. No thread at all
    means both flags False -> RED.
    """
    if has_incoming:
        return TrafficLight.GREEN
    if has_outgoing:
        return TrafficLight.YELLOW
    return TrafficLight.RED
