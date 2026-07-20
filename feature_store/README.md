# WR feature registry

`feature_store.registry.WR_FEATURE_REGISTRY` is the machine-readable v0.5B contract.
Every entry declares its source columns, transformation, entity grain, lookback,
minimum history, point-in-time availability, missing-value policy, leakage risk,
enabled status, dtype, version, and cross-season behavior.

Enabled features are candidates, not promoted model inputs. The model registry keeps
its `features` list empty until v0.5C and v0.5D evaluation supplies evidence for a
KEEP, MODIFY, or DISCARD decision.

Player rolling history follows the stable source player ID across trades and carries
across seasons. Season-to-date, team, and opponent histories reset at season
boundaries. Every outcome-derived value is shifted by at least one completed game.
Current-game targets, receptions, yards, final scores, and postgame injury data are
never prediction features.

Missing data is never silently imputed. v0.5B uses:

- `leave_null` for unavailable historical rates and counts; rolling calculations
  propagate a null when an included prior game lacks the required value;
- `fill_zero` only for deterministic indicators and known calendar fields;
- missingness indicators for snap share and route participation;
- `not_available` for candidate sources not safely supported yet.

`forward_fill` and `position_fallback` are defined registry policies but are not
applied by this version.
