"""Tests for Kenya-clipped NASA FIRMS acquisition."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("ingest_firms_fire", ROOT / "scripts" / "ingest_firms_fire.py")
firms = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(firms)


class FirmsAcquisitionTests(unittest.TestCase):
    def test_latest_request_uses_one_day_and_clips_points_to_exact_kenya_aoi(self) -> None:
        csv = (b"latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,scan,track,daynight,version\n"
               b"1.0,1.0,2026-10-14,1230,N,VIIRS,n,4.2,0.4,0.5,D,2.0NRT\n"
               b"1.0,2.5,2026-10-14,1231,N,VIIRS,n,3.1,0.4,0.5,D,2.0NRT\n")
        response = Mock(ok=True, content=csv)
        with patch.object(firms.requests, "get", return_value=response) as get:
            result = firms.acquire(None, None, "0,0,3,3", "VIIRS_SNPP_NRT", "private-key", box(0, 0, 2, 2))

        requested_url = get.call_args.args[0]
        self.assertTrue(requested_url.endswith("/VIIRS_SNPP_NRT/0,0,3,3/1"))
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["lon"], 1.0)
        self.assertEqual(result["query_mode"], "latest_day")
        self.assertEqual(result["start"], date(2026, 10, 14))
        self.assertEqual(result["aoi"], "Kenya county boundary union")

    def test_historical_request_uses_explicit_dates(self) -> None:
        response = Mock(ok=True, content=(b"latitude,longitude,acq_date,acq_time,satellite,instrument,confidence,frp,scan,track,daynight,version\n"))
        start = date(2024, 4, 21)
        with patch.object(firms.requests, "get", return_value=response) as get:
            result = firms.acquire(start, start, "0,0,3,3", "VIIRS_SNPP_NRT", "private-key", box(0, 0, 2, 2))

        self.assertTrue(get.call_args.args[0].endswith("/VIIRS_SNPP_NRT/0,0,3,3/1/2024-04-21"))
        self.assertEqual((result["start"], result["end"]), (start, start))
        self.assertEqual(result["query_mode"], "historical_period")


if __name__ == "__main__":
    unittest.main()
