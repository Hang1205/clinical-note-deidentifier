#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
if [ -x ".venv/bin/python" ]; then
  .venv/bin/python clinical_note_gui.py
else
  python3 clinical_note_gui.py
fi
status=$?
if [ "$status" -ne 0 ]; then
  echo "The app could not start. See README.md and the error above."
  read -r -p "Press Return to close. "
fi
exit "$status"
