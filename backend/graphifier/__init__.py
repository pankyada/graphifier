"""Graphifier local application backend."""

from pathlib import Path

from dotenv import load_dotenv

# Load the shared local runtime config for both API and worker. Existing
# process environment values retain precedence.
load_dotenv(Path(__file__).resolve().parents[2] / ".env.local", override=False)
