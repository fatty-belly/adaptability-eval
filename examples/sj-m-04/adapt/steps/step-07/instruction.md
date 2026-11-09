Please update the RAM log dump output so that if the in-memory cache has collapsed a run of identical consecutive records, the dumped entry shows a clear human-readable repeat note such as "(message repeated N times)". This needs to appear in both the plaintext and HTML log dump output. Entries that only occurred once should render exactly as they do now, with no extra suffix or formatting changes, so dumping logs made up of unique or otherwise distinct messages stays unchanged.

Use the suffix ` (message repeated N times)` for a repeated record.
