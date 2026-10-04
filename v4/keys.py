"""Decision-situation keys shared by the bot, the field model fit and the test clones."""

PF_CUTS = (0.02, 0.05, 0.10, 0.16, 0.24, 0.34, 0.46, 0.62, 0.80, 1.01)


def pf_sbucket(pct):
    for i, c in enumerate(PF_CUTS):
        if pct < c:
            return i
    return len(PF_CUTS) - 1


def pf_pos(seat, n):
    """0 early, 1 late (cutoff/button), 2 blinds. Button is seat 0."""
    if n == 2:
        return 1 if seat == 0 else 2
    if seat in (1, 2):
        return 2
    if seat == 0 or (n >= 4 and seat == n - 1):
        return 1
    return 0


def pf_key(nraises, pos, sb):
    return f"p{min(nraises, 2)}{pos}{sb}"


def facing_bucket(to_call, pot, nraises):
    """pot includes the bet being faced."""
    if to_call <= 0:
        return 0
    if nraises >= 2:
        return 5
    r = to_call / max(pot, 1)
    if r < 0.26:
        return 1
    if r < 0.38:
        return 2
    if r < 0.5:
        return 3
    return 4


def post_key(street, facing, bucket):
    return f"s{street}{facing}{bucket}"
