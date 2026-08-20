"""Pure formatting helpers for notification messages.

These functions hold no manager state so they can be shared by the
NotificationManager and by the binary-sensor evaluator strategies without
coupling the strategy to the manager.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..const import MAX_NOTIFICATION_LENGTH

if TYPE_CHECKING:
    from ..bayesian_evaluator import ReasonList


def generate_notification_message(base_message: str, reasons: ReasonList) -> str:
    """Construct a detailed notification message from the list of reasons.

    Reasons are appended in descending order of probability until adding the
    next one would exceed ``MAX_NOTIFICATION_LENGTH``.
    """
    sorted_reasons = sorted(reasons, reverse=True)
    message = base_message

    for _, reason in sorted_reasons:
        if len(message) + len(reason) + 2 < MAX_NOTIFICATION_LENGTH:
            message += f", {reason}"
        else:
            break
    return message
