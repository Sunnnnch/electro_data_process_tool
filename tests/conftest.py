"""Shared test configuration.

Force JSON storage backend for all tests – the existing test suite was
designed around JSON-file persistence and should not hit the SQLite path.
"""

import os

os.environ.setdefault("ELECTROCHEM_V6_STORAGE", "json")
