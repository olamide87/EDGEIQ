# Model registry

These YAML files are reviewable model definitions, not serialized model artifacts.
Every entry records the intended features, time windows, metrics, calibration,
promotion state, artifact location, and last training date. Empty values mean the
model has not earned promotion yet. Binary artifacts live under ignored `artifacts/`.
