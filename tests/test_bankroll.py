from app.services.bankroll import BankrollRules
from app.services.expected_value import Rating


def test_bankroll_uses_default_unit_for_bet_only():
    rules = BankrollRules()
    assert rules.stake_for(Rating.BET, current_weekly_exposure=0) == 5
    assert rules.stake_for(Rating.WATCH, current_weekly_exposure=0) == 0
    assert rules.stake_for(Rating.PASS, current_weekly_exposure=0) == 0


def test_bankroll_enforces_single_and_weekly_caps():
    rules = BankrollRules()
    assert rules.stake_for(
        Rating.BET, current_weekly_exposure=0, requested_stake=25
    ) == 10
    assert rules.stake_for(Rating.BET, current_weekly_exposure=48) == 2
    assert rules.stake_for(Rating.BET, current_weekly_exposure=50) == 0


def test_bankroll_reports_player_event_and_duplicate_independent_limits():
    rules = BankrollRules()
    reasons = rules.exposure_rejections(
        stake=6, weekly_exposure=45, player_exposure=10, event_exposure=15
    )
    assert any("weekly exposure" in reason for reason in reasons)
    assert any("player exposure" in reason for reason in reasons)
    assert any("event exposure" in reason for reason in reasons)
