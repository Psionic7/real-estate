"""Display units for exclusive apartment area; stored values remain square metres."""

M2_PER_PYEONG = 3.305785


def to_display_area(area_m2, unit):
    return area_m2 / M2_PER_PYEONG if unit == "평" else area_m2


def to_square_metres(value, unit):
    return value * M2_PER_PYEONG if unit == "평" else value


def area_label(unit, prefix="전용면적"):
    return f"{prefix}({unit})"


def format_area(value_m2, unit, decimals=None):
    if decimals is None:
        decimals = 1 if unit == "평" else 0
    return f"{to_display_area(value_m2, unit):.{decimals}f}{unit}"


def format_area_range(min_m2, max_m2, unit, decimals=None):
    if decimals is None:
        decimals = 1 if unit == "평" else 0
    minimum = to_display_area(min_m2, unit)
    maximum = to_display_area(max_m2, unit)
    if f"{minimum:.{decimals}f}" == f"{maximum:.{decimals}f}":
        return format_area(min_m2, unit, decimals)
    return f"{minimum:.{decimals}f}~{maximum:.{decimals}f}{unit}"
