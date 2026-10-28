"""Runtime configuration for the first milestone."""

import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./techledger.db")
SOURCE_TIMEOUT_SECONDS = float(os.getenv("SOURCE_TIMEOUT_SECONDS", "15"))
SOURCE_MAX_BYTES = int(os.getenv("SOURCE_MAX_BYTES", str(2 * 1024 * 1024)))
SOURCE_MAX_REDIRECTS = int(os.getenv("SOURCE_MAX_REDIRECTS", "3"))
WEB_ORIGIN = os.getenv("WEB_ORIGIN", "http://localhost:3000")
RESEARCH_MAX_EVIDENCE = int(os.getenv("RESEARCH_MAX_EVIDENCE", "6"))
RESEARCH_MODEL_TIMEOUT_SECONDS = float(os.getenv("RESEARCH_MODEL_TIMEOUT_SECONDS", "20"))
RESEARCH_MAX_OUTPUT_TOKENS = int(os.getenv("RESEARCH_MAX_OUTPUT_TOKENS", "256"))
