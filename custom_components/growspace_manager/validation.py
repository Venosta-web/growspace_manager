from datetime import date, datetime

import voluptuous as vol


def valid_date_or_none(value):
    """Validate that a value is a valid date or None for voluptuous schemas.

    Args:
        value: The value to validate.

    Returns:
        The parsed date object or None.

    Raises:
        vol.Invalid: If the value is not a valid date format.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value

    value_str = str(value).replace("Z", "")

    # Try parsing as datetime first (most specific)
    try:
        return datetime.fromisoformat(value_str)
    except ValueError:
        pass

    # Try parsing as date
    try:
        return date.fromisoformat(value_str)
    except ValueError:
        raise vol.Invalid(
            f"'{value}' is not a valid date or ISO format string"
        ) from None


def valid_growspace_id(value):
    """Validate that a value is a non-empty string for a growspace ID.

    Args:
        value: The value to validate.

    Returns:
        The validated string.

    Raises:
        vol.Invalid: If the value is not a valid growspace ID.
    """

    if not isinstance(value, str) or not value:
        raise vol.Invalid("Growspace ID cannot be empty")
    return value
