# External sources

Normal startup fetches pinned game source into Docker's project-scoped `sources`
volume. No host checkout is required here. Existing ignored checkouts can remain
for manual research; the builder does not read or modify them.

See the [game catalog and workflow](../docs/sameboy.md#source-selection-and-verification)
for repositories, pinned revisions, and source overrides.
