import os
import tempfile

# Point the app at a throwaway data dir before any backend module is imported.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="filinglens-test-")
