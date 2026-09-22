# Trainer data

A CSV copy of 2026 Main Season, Session 6, made by `tools/snapshot_training.py`: the Config,
Skills, Clinic_Data and cabin act sheets, and the session's Staff Categories and Offerings.
The requests and the published schedules are left out; the trainer never needs them.

One thing is not as the live sheet had it: `config/mapping_buddy.csv` is written by hand, so
that the mapping problems have buddies to look up. The live one named a counselor as a buddy,
which the Mappings tab does not allow, and pruning it left the table empty.
