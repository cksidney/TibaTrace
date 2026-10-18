# POS version format

POS releases use a numeric major version and one digit each for minor and patch:
`1.0.8 → 1.0.9 → 1.1.0 → 1.1.1` and `1.9.9 → 2.0.0`.
Do not publish versions such as `1.0.10` or `1.10.0`. Existing immutable tags
are retained as history. The first release under this policy is `1.1.0`.

Windows and Android keep separate, monotonically increasing integer build
numbers. Never derive them from the display version or reset them on rollover.
Both platforms store version/build in their package.json; Android Gradle reads
those values directly. Keep package-lock.json aligned. Backend release-candidate
identifiers remain a separate server release track.

Run `python3 scripts/pos_version.py` to check both platforms and their lock
entries. Run `python3 scripts/pos_version.py --next 1.0.9` to get `1.1.0`.
Release pipelines reject incompatible versions and mismatched platform tags.
