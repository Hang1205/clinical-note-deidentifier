# Build verification — 2026-10-07

Application: Clinical Note Deidentifier 1.0.0.

Tested on Windows x64 with Python 3.12.0 and Tkinter, Presidio Analyzer/Anonymizer 2.2.364, spaCy 3.8.16 and en_core_web_lg 3.8.0.

- Ten automated tests passed against the actual local NLP model, including fictional PHI detection; CSV, TSV and gzip processing; identifier exclusion; consistent random patient pseudonyms; multiline records; spreadsheet escaping; missing model; invalid inputs; no overwrite; cancellation; custom recognizers; and blocked network access.
- A fresh isolated Python environment installed all 57 bundled wheels with Python socket connections disabled, `--no-index`, and only the local wheelhouse. The same ten tests passed in that environment.
- The Tkinter GUI completed a real asynchronous preview and two-record batch using fictional notes. Completed outputs and audit counts were checked. All three tabs and action/status areas were checked at the minimum 980 × 740 window size.
- Desktop screenshot capture was unavailable in this execution environment. No screenshot-based visual check is claimed.
- macOS execution, clinical accuracy on institutional notes, and compliance status have not been established. These functional tests are not a clinical validation study.

Python and Tkinter are prerequisites, not bundled installers. The Windows wheelhouse targets CPython 3.12, Windows x64, and cannot be used as a Mac installation kit. Refer to README.md for Mac/source setup.

The Windows offline kit includes MANIFEST.json with SHA-256 hashes of the application and bundled files. SHA256SUMS.txt beside the ZIP files records archive hashes.
