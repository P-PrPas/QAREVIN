# Decisions and measurements

- 2026-11-06: qarevin/ is the Git root; origin is https://github.com/P-PrPas/QAREVIN.git.
  Existing empty remote initialized with documentation on main; implementation stays in unmerged PRs.
- Python minimum 3.12: pinned NumPy 2.5 requires 3.12. Local interpreter is 3.14.4; CI also covers 3.12.
- Parameter-only trusted strategies first. No generated Python execution until real sandbox tests pass.
- Synthetic contract/session/cost settings stay unverified; no market or broker evidence available.
- Initial host snapshot from planning: total RAM 6.7 GiB, available ~1.8 GiB, swap ~4 GiB used,
  available disk ~151 GiB. Snapshot is not a reservation. Run preflight before every heavy job.
- F0 SQLite migration establishes audit/schema version. Experiment/job entities are added in F2/F3.
