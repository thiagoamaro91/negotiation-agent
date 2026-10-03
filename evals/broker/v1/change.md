broker.py --policy ours (BenchPolicy) instead of the stall

Confirmation run, no hill-climb: same 298 cases as the 50-seed baseline (same frozen copy of today's log, so the same real sessions and the same fitted@hash refit). Only the bench policy changes: BenchPolicy waits on offers whose shown expiry is later than the session end; with every real expiry equal to the session end it plays the stall's exact rule, so it can only differ on *_expiry_exact and the other lab scenarios.
