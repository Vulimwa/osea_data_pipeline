import { useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { cn } from '../lib/cn';
import {
  PILOT_DATASET,
  fetchAssetCriticality,
  fetchAssetExposure,
  fetchAssetVulnerability,
  fetchPilotAssets,
} from '../lib/api';

function toneClass(label: string | null | undefined): string {
  const v = (label || '').toLowerCase();
  if (!v || v === 'unknown' || v === 'not_assessed' || v === 'insufficient_data') return 'tone-unk';
  if (v === 'low' || v === 'not_exposed' || v === 'assessed') return 'tone-safe';
  if (v === 'moderate' || v === 'exposed') return 'tone-warn';
  if (v === 'high' || v === 'very_high') return 'tone-hot';
  return '';
}

export function EvidencePage() {
  const { assetId } = useParams();
  const navigate = useNavigate();

  const pilotQ = useQuery({
    queryKey: ['assets-pilot'],
    queryFn: fetchPilotAssets,
    retry: 1,
  });

  const asset = (pilotQ.data ?? []).find((a) => a.id === assetId) ?? null;

  const detailQ = useQuery({
    queryKey: ['asset-detail', assetId],
    enabled: Boolean(assetId),
    queryFn: async () => {
      const id = assetId as string;
      const [exposure, vulnerability, criticality] = await Promise.all([
        fetchAssetExposure(id),
        fetchAssetVulnerability(id),
        fetchAssetCriticality(id).catch(() => ({
          assetId: id,
          status: 'not_assessed',
          data: [],
        })),
      ]);
      return { exposure, vulnerability, criticality };
    },
  });

  if (!assetId || !asset) {
    return (
      <div className="asset-page page">
        <p className="kicker">Evidence</p>
        <h1>No asset selected</h1>
        <p className="meta">Open the map, pick a pilot asset, then view evidence.</p>
        <div className="cta-row">
          <calcite-button kind="brand" onClick={() => navigate('/map')}>
            Open map
          </calcite-button>
        </div>
      </div>
    );
  }

  const exposure = detailQ.data?.exposure.data ?? null;
  const vulnerability = detailQ.data?.vulnerability.data?.[0] ?? null;
  const criticality = detailQ.data?.criticality.data?.[0] ?? null;
  const flood = exposure?.find((row) => row.hazard_type === 'flood');
  const heat = exposure?.find((row) => row.hazard_type === 'heat');
  const wildfire = exposure?.find((row) => row.hazard_type === 'wildfire');
  const floodScore = flood?.provenance?.exposure;
  const isPilot = asset.properties.sourceDataset === PILOT_DATASET;
  const detailStatus =
    detailQ.data?.vulnerability.status || detailQ.data?.exposure.status || null;

  return (
    <div className="asset-page page">
      <p className="kicker">
        {isPilot ? 'Pilot · osm_kano_pilot' : asset.properties.sourceDataset || 'inventory'}
        {detailStatus ? ` · ${detailStatus}` : ''}
        {detailQ.isFetching ? ' · loading…' : ''}
      </p>
      <h1>{asset.properties.name || 'Unnamed asset'}</h1>
      <p className="meta">
        {asset.properties.assetType}
        {asset.properties.sourceFeatureId ? ` · ${asset.properties.sourceFeatureId}` : ''}
      </p>

      <div className="cta-row">
        <calcite-button appearance="outline" kind="neutral" onClick={() => navigate('/map')}>
          Back to map
        </calcite-button>
      </div>

      {detailQ.isLoading && (
        <div className="mt-8">
          <calcite-loader label="Loading evidence" />
        </div>
      )}

      <div className="metrics">
        <div className="metric">
          <label>Flood exposure</label>
          <div
            className={cn(
              'value',
              toneClass(floodScore == null ? flood?.exposure_status || 'unknown' : 'exposed'),
            )}
          >
            {flood == null
              ? 'not assessed'
              : floodScore == null || Number.isNaN(Number(floodScore))
                ? flood.exposure_status
                : Number(floodScore).toFixed(3)}
          </div>
          <p className="note">
            {flood
              ? [
                  flood.exposure_status,
                  flood.provenance?.observed && `observed ${flood.provenance.observed}`,
                  flood.provenance?.method,
                ]
                  .filter(Boolean)
                  .join(' · ')
              : 'No flood row for this asset'}
          </p>
        </div>

        <div className="metric">
          <label>Vulnerability</label>
          <div
            className={cn(
              'value',
              toneClass(vulnerability?.vulnerability_class || vulnerability?.status),
            )}
          >
            {vulnerability?.score == null
              ? vulnerability?.vulnerability_class || vulnerability?.status || 'not assessed'
              : `${Number(vulnerability.score).toFixed(3)} · ${
                  vulnerability.vulnerability_class || '—'
                }`}
          </div>
          <p className="note">{vulnerability?.method || '—'}</p>
        </div>

        <div className="metric">
          <label>Criticality</label>
          <div className={cn('value', toneClass(criticality?.status))}>
            {criticality?.score == null
              ? criticality?.status || 'not assessed'
              : String(criticality.score)}
          </div>
          <p className="note">
            {criticality?.method || 'Withheld without topology / served-load evidence'}
          </p>
        </div>

        <div className="metric">
          <label>Heat</label>
          <div className={cn('value', toneClass(heat?.exposure_status || 'unknown'))}>
            {heat?.exposure_status || 'not assessed'}
          </div>
        </div>

        <div className="metric">
          <label>Wildfire</label>
          <div className={cn('value', toneClass(wildfire?.exposure_status || 'unknown'))}>
            {wildfire?.exposure_status || 'not assessed'}
          </div>
        </div>
      </div>
    </div>
  );
}
