"""Shared Earth Engine authentication used by OSEAS processing scripts."""
from gee.auth import initialize_earth_engine, is_gee_available

__all__ = ["initialize_earth_engine", "is_gee_available"]
