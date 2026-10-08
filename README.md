# Clinical Note Deidentifier — local desktop GUI

Batch PHI detection and typed redaction for English clinical notes using Presidio and a locally installed spaCy NER model. Windows and Mac source launchers are included. The Windows offline kit targets Python 3.12, Windows x64. Actual macOS execution has not been tested.

**Desktop GUI:** choose a note export, select the text column, preview detected identifiers, and run batch redaction. The tabs cover Batch processing, Preview & review, and Model & offline setup. Processing uses the local computer; original files are preserved.

## Downloads

- [Windows offline kit, v1.0.0 — approximately 452 MB](https://github.com/Hang1205/clinical-note-deidentifier/releases/download/v1.0.0/Clinical_Note_Deidentifier_Windows_Offline.zip): includes all dependency wheels and the English model; Python 3.12 x64 must already be installed.
- [Windows/Mac source package, v1.0.0](https://github.com/Hang1205/clinical-note-deidentifier/releases/download/v1.0.0/Clinical_Note_Deidentifier_Source.zip): dependencies and model must be installed separately.
- [Release notes and SHA-256 checksums](https://github.com/Hang1205/clinical-note-deidentifier/releases/tag/v1.0.0).

Install from a release for the offline workflow. GitHub's **Code → Download ZIP** contains source code and does not include `wheelhouse/`.

## Windows offline kit

1. Install **Python 3.12 64-bit**, including Tkinter and the Windows Python launcher, through your institution's approved process. Python itself is not included in this kit.
2. Extract the ENTIRE Windows offline ZIP to a writable local application folder. Keep `wheelhouse/` and the lock file with the scripts.
3. Run `Install_Offline_Windows.cmd`. It creates `.venv/` and installs packages from the bundled wheel files with `--no-index`; no internet connection is used.
4. Run `Start_Windows.cmd`.

The extracted kit is roughly 452 MB (431 MiB); the environment needs additional disk space after installation. Allow at least 2 GB of free space for the kit and environment, plus space for your notes and outputs. The model is `en_core_web_lg` 3.8.0; Presidio is 2.2.364 and spaCy is 3.8.16. Review `requirements_windows_py312.lock.txt` for the complete versions.

## Source package / Mac setup

The small source ZIP does NOT include dependencies or the NLP model. Use Python 3.12 with Tkinter. In the application folder, create a virtual environment and, while connected or through an approved local package mirror, run:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m spacy download en_core_web_lg
.venv/bin/python clinical_note_gui.py
```

On Windows, substitute `py -3.12` for `python3` and `.venv\Scripts\python.exe` for `.venv/bin/python`. On Mac, the included `Start_Mac.command` uses `.venv/bin/python` when present; `chmod +x Start_Mac.command` enables the optional launcher. `python3 -m tkinter` verifies Tkinter availability.

For a fully disconnected Mac, prepare wheels and the model on a connected machine matching the Mac CPU architecture, OS and Python version. Transfer them through the approved process and install with `pip install --no-index --find-links wheelhouse ...`. The Windows wheelhouse cannot install Mac binary dependencies. Models must be available locally before launching detection. You can specify an installed model name or a complete extracted model directory on Model & offline setup. Model changes need new local validation.

## Process notes

1. Select a CSV/TSV export (optionally `.gz`), a TXT file, or a folder of TXT files. TXT folders include only top-level `.txt` files, not subfolders or symlinks.
2. For tables, choose the **note text column**. Headers must be unique and nonempty; UTF-8 is the default. Select another input encoding if necessary.
3. Optionally select a **patient identifier column**. It is replaced by a random consistent pseudonym within this run. No mapping is saved, and pseudonyms will differ on future runs. Join other data only through a separately approved linkage process.
4. Choose a NEW output folder, outside the input TXT folder. Originals are read, never modified.
5. Check the local model, then preview a note. You can also use the fictional example; do not paste real notes into online demonstrations.
6. Acknowledge local review and run batch redaction. The interface remains responsive. Cancel stops between records; model loading or the current note may take time to finish.
7. Review completed outputs locally before any downstream analysis or sharing.

## Output files

- `notes_redacted.csv`: record number, optional random patient pseudonym, redacted text, candidate span count and review status. **Unselected input columns, original filenames and original record IDs are not copied.** Multiline notes are quoted correctly. Formula-like note values are prefixed with an apostrophe for spreadsheet safety.
- `review.csv`: record numbers, counts and flags only; no source spans or original identifiers. All records require review. Notes without detections are explicitly marked for review; blank notes are distinguished.
- `audit.json`: aggregate counts, model/package versions, threshold, local rule fingerprint, completion status and timestamps. No source note text or original file paths are logged. Candidate span counts can exceed replacement counts because detections can overlap.

Failed/cancelled runs retain a `OUTPUT.incomplete-...` folder and failed/cancelled audit. Partial files are NOT completed de-identification results. A completed destination appears only after a successful run. Existing destinations are rejected. Keep originals stable during processing. Notes above one million characters are rejected rather than silently truncated. Source linkage is not preserved unless you select the patient-ID column; original note IDs are discarded.

## Detection and clinical review

The local analyzer combines general English NER with Presidio's recognizers and additional patterns for labeled MRNs, patient/account/accession identifiers, common street addresses and written ages above 89. Dates are replaced, not shifted. Detection threshold defaults to 0.35 and must be evaluated on local notes. Scores are not calibrated probabilities of complete de-identification.

Supply a local JSON file based on `custom_recognizers.example.json` for institution-specific formats. The example is deliberately a generic sample, not a validated hospital configuration. Do not put private identifier dictionaries or real notes in a code repository.

Detected spans overlapping clinical eponyms such as Fontan, Glenn and Norwood are flagged for review. They are still redacted: there is no broad clinical-term whitelist that could accidentally retain a patient's name. Compare the original and redacted notes inside your approved environment. Check both missed identifiers and altered clinical meaning. A general spaCy model is not a specialist clinical PHI model. Patient initials, unusual identifiers/date/address formats, geographic details, rare identifying narratives and other PHI may be missed. Validate every identifier category on representative, manually annotated local notes before reliance. Routine rule tuning and expert review are necessary.

**This application does not certify HIPAA Safe Harbor, Expert Determination, anonymity, or fitness for clinical use.** A private repository or offline workstation does not itself establish an approved research environment. Institutional privacy review governs releases and permissible retention of dates or linkage. The app removes detected dates; it does not implement a longitudinal date-shifting protocol.

## Offline behavior

The GUI and detector block Python socket connections. NLP loading explicitly uses an installed/local model and bypasses Presidio's automatic model download. No cloud recognizers or hosted APIs are configured. Run with the network disconnected to verify your environment. This application-level block is not an OS firewall or a guarantee about unrelated applications. Installation can use internet only in the explicit source setup path; the offline installer uses bundled files only.

## Verification

The Windows build passed 10 automated tests against the real local model, an asynchronous GUI preview and two-note batch workflow, and layout checks at its minimum window size. A separate clean virtual environment installed all 57 bundled packages with Python network connections blocked and passed the same tests. These checks used fictional notes only. See `BUILD_VERIFICATION.md` for the tested configuration.

Run `.venv\Scripts\python.exe -m unittest discover -s . -p test_deid.py` on Windows, or `.venv/bin/python -m unittest discover -s . -p test_deid.py` on Mac. Tests use only fictional notes and check real local detection, batch integrity, identifier exclusion, pseudonyms, CSV quoting, failure/cancellation, and blocked network access. No real clinical notes were processed during development. Clinical accuracy and physical macOS behavior are not established by these tests.

## Components and guidance

- Presidio: https://presidio.dataprivacystack.org/analyzer/
- spaCy model: https://spacy.io/models/en
- HHS de-identification guidance: https://www.hhs.gov/hipaa/for-professionals/special-topics/de-identification/index.html

This wrapper is an independent research utility and does not imply endorsement by the component developers. Third-party packages retain their own licenses. The wheel distributions include package license metadata; the offline kit also includes third-party notices.

## Cite this software

Xu, H. (2026). *Clinical Note Deidentifier: Offline Desktop GUI* (Version 1.0.0) [Computer software]. GitHub. https://github.com/Hang1205/clinical-note-deidentifier

GitHub's **Cite this repository** menu reads `CITATION.cff`. No DOI has been assigned; this is a software release, not a peer-reviewed clinical validation publication. Cite the software version actually used and separately acknowledge Presidio and spaCy when describing the detection method.

The wrapper source is licensed under MIT; see `LICENSE`. Dependency and model licenses are separate; see `THIRD_PARTY_NOTICES.md` and the release kit's `third_party/` directory.
