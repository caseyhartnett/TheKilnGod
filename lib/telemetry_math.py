def avg(values):
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def bool_pct(values):
    if not values:
        return 0.0
    return avg([1.0 if v else 0.0 for v in values]) * 100.0


def within_tolerance_pct(values, tolerance):
    if not values:
        return 0.0
    return (sum(1 for value in values if abs(value) <= tolerance) / float(len(values))) * 100.0


def switch_count(binary_values):
    if len(binary_values) <= 1:
        return 0
    count = 0
    prev = 1 if binary_values[0] else 0
    for value in binary_values[1:]:
        now = 1 if value else 0
        if now != prev:
            count += 1
        prev = now
    return count


def switches_per_hour(total_switches, runtime_seconds):
    if runtime_seconds <= 0:
        return 0.0
    return float(total_switches) / (float(runtime_seconds) / 3600.0)

