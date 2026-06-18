"""Flat feature package.

Each non-private module can expose `FEATURE = FeatureSpec(...)` or
`get_feature() -> FeatureSpec`. Disabled features use `enabled=False`.
All trigger types are declared through `FeatureSpec.subscriptions`.
"""
