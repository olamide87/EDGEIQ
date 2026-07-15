from dataclasses import dataclass

from app.services.expected_value import Rating


@dataclass(frozen=True)
class BankrollRules:
    paper_bankroll: float = 1000.0
    default_unit: float = 5.0
    max_single_recommendation: float = 10.0
    max_weekly_exposure: float = 50.0
    max_player_exposure: float = 15.0
    max_event_exposure: float = 20.0

    def stake_for(
        self,
        rating: Rating,
        *,
        current_weekly_exposure: float,
        requested_stake: float | None = None,
    ) -> float:
        if current_weekly_exposure < 0:
            raise ValueError("Weekly exposure cannot be negative.")
        if rating is not Rating.BET:
            return 0.0

        stake = self.default_unit if requested_stake is None else requested_stake
        if stake < 0:
            raise ValueError("Requested stake cannot be negative.")
        remaining = max(0.0, self.max_weekly_exposure - current_weekly_exposure)
        return round(min(stake, self.max_single_recommendation, remaining), 2)

    def exposure_rejections(
        self, *, stake: float, weekly_exposure: float,
        player_exposure: float, event_exposure: float,
    ) -> list[str]:
        checks = (
            (stake, self.max_single_recommendation, "single stake"),
            (weekly_exposure + stake, self.max_weekly_exposure, "weekly exposure"),
            (player_exposure + stake, self.max_player_exposure, "player exposure"),
            (event_exposure + stake, self.max_event_exposure, "event exposure"),
        )
        return [f"Exceeds maximum {label} of ${maximum:g}." for value, maximum, label in checks
                if value > maximum]
