# Dependency credits and redistribution notices

This GUI uses:

- **Presidio Analyzer and Anonymizer 2.2.364**, Presidio Contributors, MIT license. Documentation: https://presidio.dataprivacystack.org/ . Source: https://github.com/data-privacy-stack/presidio .
- **spaCy 3.8.16**, Explosion and contributors, MIT license. Documentation and source: https://spacy.io/ and https://github.com/explosion/spaCy .
- **en_core_web_lg 3.8.0**, Explosion's general English model. Model details: https://spacy.io/models/en . Model and training-source licenses are included in the model wheel and copied into the offline release's `third_party/` directory.
- The transitive dependencies pinned in `requirements_windows_py312.lock.txt`. Their individual licenses apply independently of the wrapper's MIT license.

The repository contains this wrapper's source; it does not vendor dependency wheels. The offline release includes the original, unmodified wheel distributions, their embedded license files, copies of available notices, and `third_party/COMPONENTS.json`. Review those notices before redistributing the offline kit. Credits do not imply endorsement or clinical validation by the upstream projects.
