"""Pytest configuration ensuring test mode environment."""

import os

os.environ["FAULTLINE_ENV"] = "test"
