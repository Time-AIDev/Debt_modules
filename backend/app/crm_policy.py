"""Deployment policy for the Won-only staging customer book."""
import os


def won_only():
    return os.environ.get("CRM_WON_ONLY", "").lower() in ("1", "true", "yes")
