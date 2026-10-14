"""OSEAS environment configuration and Earth Engine asset registry."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AssetSpec:
    key: str
    label: str
    env_key: str
    category: str
    target: str


ASSETS = (
    AssetSpec("kenya_counties", "Kenya administrative/county export", "GEE_ASSET_KENYA_COUNTIES", "administrative_boundary", "county"),
    AssetSpec("distribution_transformers", "Distribution transformers", "GEE_ASSET_DISTRIBUTION_TRANSFORMERS", "distribution_transformer", "energy_asset"),
    AssetSpec("existing_mini_grids", "Existing mini-grids", "GEE_ASSET_EXISTING_MINI_GRIDS", "mini_grid_existing", "energy_asset"),
    AssetSpec("healthcare_facilities", "Healthcare facilities", "GEE_ASSET_HEALTHCARE_FACILITIES", "healthcare_facility", "critical_service"),
    AssetSpec("mini_grids_under_development", "Mini-grids under development", "GEE_ASSET_MINI_GRIDS_UNDER_DEVELOPMENT", "mini_grid_development", "energy_asset"),
    AssetSpec("power_stations", "Power stations", "GEE_ASSET_POWER_STATIONS", "power_station", "energy_asset"),
    AssetSpec("primary_substations", "Primary substations", "GEE_ASSET_PRIMARY_SUBSTATIONS", "primary_substation", "energy_asset"),
    AssetSpec("schools", "Schools", "GEE_ASSET_SCHOOLS", "school", "critical_service"),
    AssetSpec("transmission_lines_132kv", "Transmission lines 132 kV", "GEE_ASSET_TRANSMISSION_LINES_132KV", "transmission_line", "network_line"),
    AssetSpec("transmission_lines_220kv", "Transmission lines 220 kV", "GEE_ASSET_TRANSMISSION_LINES_220KV", "transmission_line", "network_line"),
    AssetSpec("transmission_lines_33kv", "Transmission lines 33 kV", "GEE_ASSET_TRANSMISSION_LINES_33KV", "transmission_line", "network_line"),
    AssetSpec("transmission_lines_66kv", "Transmission lines 66 kV", "GEE_ASSET_TRANSMISSION_LINES_66KV", "transmission_line", "network_line"),
    AssetSpec("unidentified_grid_network", "Unidentified grid network", "GEE_ASSET_UNIDENTIFIED_GRID_NETWORK", "unidentified_grid_network", "network_line"),
    AssetSpec("kenya_wards", "Kenya wards", "GEE_ASSET_KENYA_WARDS", "administrative_boundary", "ward"),
    AssetSpec("kenya_rivers", "Kenya rivers (OSEA Earth Engine asset)", "GEE_ASSET_KENYA_RIVERS", "river", "hydrography"),
    AssetSpec("kenya_lakes", "Kenya lakes (OSEA Earth Engine asset)", "GEE_ASSET_KENYA_LAKES", "lake", "hydrography"),
    AssetSpec("kenya_flood_2023_reference", "Kenya November 2023 flood reference polygons", "GEE_ASSET_KENYA_FLOOD_2023", "flood_reference", "flood_reference"),
)


def configured_assets() -> list[tuple[AssetSpec, str]]:
    return [(spec, os.environ[spec.env_key].strip()) for spec in ASSETS if os.getenv(spec.env_key, "").strip()]


def missing_asset_keys() -> list[str]:
    return [spec.env_key for spec in ASSETS if not os.getenv(spec.env_key, "").strip()]


def database_url() -> str:
    return (os.getenv("DB_URL", "").strip() or os.getenv("DATABASE_URL", "").strip()
            or os.getenv("SUPABASE_DB_URL", "").strip())


def nasa_earthdata_token() -> str:
    """Accept the project token name already used in the operator's .env."""
    return (os.getenv("NASA_EARTHDATA_TOKEN", "").strip()
            or os.getenv("LAAD_TOKEN_NASA", "").strip())
