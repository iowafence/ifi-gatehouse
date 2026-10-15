# legacy_fixtures (quarantined)

Older three-crew stand-ins kept only for named legacy tests. **Do not use for any demo view.** The authoritative crew data is the pinned rate book v2.3.0 (`config/ratebook_reference_2.3.0.fictional.xlsx`): fleet CR11 104%, CR12 94%, CR13 88%, CR14 97%; drilling requires role R4, so CR11 and CR12 are ineligible.

* `legacy_crews.py`, `crews.legacy.json`: pre-rate-book crew stand-in (claims Crew 2 can drill).
* `legacy_3crew_testbook.fictional.xlsx`, `build_legacy_testbook.py`: test-only rate book with its own CR1-CR3 ids, used to test engine-level invalidation rules.

Enforced by `tests/test_crew_views_consistent.py`: no public route may reference these ids or roster.
