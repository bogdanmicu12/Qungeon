"""Browser entry point for Qungeon's bundled Unitary alpha package.

The game only uses ``unitary.alpha``. The desktop package's top-level cloud-engine
imports are intentionally omitted because they are unrelated to gameplay and cannot
run in a browser. All quantum gameplay modules under ``unitary.alpha`` are copied
unchanged from the pinned upstream checkout.
"""
