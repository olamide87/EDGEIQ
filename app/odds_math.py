def american_to_decimal(american_odds: int) -> float:
    if american_odds == 0:
        raise ValueError("American odds cannot be zero.")
    if american_odds > 0:
        return 1 + american_odds / 100
    return 1 + 100 / abs(american_odds)


def implied_probability(american_odds: int) -> float:
    if american_odds == 0:
        raise ValueError("American odds cannot be zero.")
    if american_odds > 0:
        return 100 / (american_odds + 100)
    return abs(american_odds) / (abs(american_odds) + 100)
