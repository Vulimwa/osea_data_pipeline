# OSEAS Earth Engine asset audit

Live read-only audit completed on 13 October 2026. All 14 configured IDs resolved as Earth Engine `TABLE` assets under `projects/osea-hack/assets/osea/`. The audit read metadata, sampled feature geometry/properties and queried each full feature count. It did not write to Supabase.

| Dataset | Features | Sample geometry | Identifier or useful fields observed |
|---|---:|---|---|
| Kenya administrative/county export (`KenyaExport`) | 47 | Polygon | `GAUL1_CODE`, `GAUL1_NAME`, `GAUL0_CODE`, `GAUL0_NAME`; the 47 rows and GAUL1 fields are consistent with county boundaries |
| Distribution transformers | 57,360 | Point | `OBJECTID`, `County2`, `Feeder_o28`, `Substati9` |
| Existing mini-grids | 22 | Point | `Name`, `County`, `Constituen`, `Status`, `Pot_Cust` |
| Healthcare facilities | 10,013 | Point | `OBJECTID`, `Facility_N`, `County`, `Sub_County`, `Type`, `Latitude`, `Longitude` |
| Mini-grids under development | 26 | Point | `Name`, `County`, `Status`, `Pot_Cust`, `Comments` |
| Power stations | 40 | Point | `OBJECTID`, `Name`, `Type`, `Capacity_M`, `Status`, `Year` |
| Primary substations | 264 | Point | `OBJECTID`, `Name8`, `Name_IMS11`, `County2`, `Availabi39` |
| Schools | 37,930 | Point | `CODE`, `SCHOOL_NAM`, `County`, `DISTRICT`, `SUB_COUNTY`, `Ward`, `LEVEL` |
| Transmission lines 132 kV | 100 | LineString | `OBJECTID`, `voltage40`, `Length_km`, `County2` |
| Transmission lines 220 kV | 18 | LineString | `OBJECTID`, `voltage40`, `Length_km`, `County2` |
| Transmission lines 33 kV | 31,759 | LineString | `OBJECTID`, `voltage48`, `Length_m_`, `County2` |
| Transmission lines 66 kV | 229 | LineString | `OBJECTID`, `Voltage47`, `Length_km`, `County2` |
| Unidentified grid network | 12,446 | LineString | `Length_m`, `Status`, `RCC1` |
| Kenya wards (`kenya_wards`) | 1,450 | Polygon | `uid`, `cuid`, `gid`, `ward`, `county`, `subcounty`, `pop2009` |

## Data handling decisions

- County and ward polygons are loaded into `administrative_units`, with `GAUL1_CODE` and `uid` as stable codes respectively. Names are retained as attributes; identifiers do not rely on name matching.
- Transformer, healthcare, power-station, substation, school, and line assets expose `OBJECTID` or `CODE` fields suitable for stable source IDs. Ward and county stable IDs are used where available. Mini-grid IDs use Earth Engine row IDs when the source has no distinct ID field.
- Transformer, substation and most power-station samples do not expose an obvious numeric capacity field with documented units. These capacities remain null; the original properties are preserved.
- Transmission line attribute field names vary between voltage assets. Voltage class is taken from the source dataset name; the source field values remain unmodified in `source_properties`.
- The KenyaExport schema uses GAUL1 first-level administrative fields and 47 rows. The boundary source is therefore suitable as the candidate Kenya county layer, subject to polygon visual review after ingestion.
- The ward asset includes a 2009 population property. It is not treated as current population or exposed population without population-vintage validation and an explicit spatial method.

The machine-readable full property schemas were emitted by the CLI during the audit. Run `npm run oseas:audit` to regenerate them after source assets change.
