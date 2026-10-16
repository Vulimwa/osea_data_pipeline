import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { cn } from '../lib/cn';
import {
  PILOT_DATASET,
  fetchAssetCriticality,
  fetchAssetExposure,
  fetchAssetServiceDependencies,
  fetchAssetVulnerability,
  fetchAdministrativeSummary,
  fetchPilotAssets,
  type AssetFeature,
} from '../lib/api';

function toneClass(label: string | null | undefined): string {
  const v = (label || '').toLowerCase();
  if (!v || v === 'unknown' || v === 'not_assessed' || v === 'insufficient_data') return 'tone-unk';
  if (v === 'low' || v === 'not_exposed' || v === 'assessed') return 'tone-safe';
  if (v === 'moderate' || v === 'exposed') return 'tone-warn';
  if (v === 'high' || v === 'very_high') return 'tone-hot';
  return '';
}

function asRecord(value: unknown): Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function parameterLabel(value: string): string {
  return value.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_-]/g, ' ');
}

function parameterValue(value: unknown): string {
  const text =
    value != null && typeof value === 'object' ? JSON.stringify(value) : String(value ?? '');
  return text.length > 240 ? `${text.slice(0, 237)}…` : text;
}

export function EvidencePage() {
  const { assetId, level, unitId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const routedAsset = (location.state as { asset?: AssetFeature } | null)?.asset ?? null;
  const administrativeLevel = level === 'ward' || level === 'county' ? level : null;

  const administrativeSummaryQ = useQuery({
    queryKey: ['administrative-summary', administrativeLevel, unitId],
    enabled: Boolean(administrativeLevel && unitId),
    queryFn: async () => {
      if (!administrativeLevel || !unitId) throw new Error('Administrative unit is required.');
      return fetchAdministrativeSummary(administrativeLevel, unitId);
    },
    retry: 1,
  });

  const pilotQ = useQuery({
    queryKey: ['assets-pilot'],
    queryFn: fetchPilotAssets,
    enabled: Boolean(assetId && !unitId && !routedAsset),
    retry: 1,
  });

  const asset = routedAsset ?? (pilotQ.data ?? []).find((a) => a.id === assetId) ?? null;

  const detailQ = useQuery({
    queryKey: ['asset-detail', assetId],
    enabled: Boolean(assetId && !unitId),
    queryFn: async () => {
      const id = assetId as string;
      const [exposure, vulnerability, criticality, dependencies] = await Promise.all([
        fetchAssetExposure(id),
        fetchAssetVulnerability(id),
        fetchAssetCriticality(id),
        fetchAssetServiceDependencies(id),
      ]);
      return { exposure, vulnerability, criticality, dependencies };
    },
  });

  if (unitId && administrativeLevel) {
    const properties = administrativeSummaryQ.data?.properties;
    const vulnerabilitySummary = asRecord(properties?.vulnerabilitySummary);
    const assetCounts = asRecord(vulnerabilitySummary.assetCounts);
    const hazardCounts = asRecord(vulnerabilitySummary.hazardCounts);
    const provenance = asRecord(vulnerabilitySummary.provenance);
    const missingEvidence = Array.isArray(provenance.missingEvidence)
      ? provenance.missingEvidence
      : [];
    const hazardRows = Object.entries(hazardCounts).map(([hazard, value]) => {
      const counts = asRecord(value);
      return {
        hazard,
        exposed: Number(counts.exposedAssets ?? 0),
        unknown: Number(counts.unknownAssets ?? 0),
        measured: Number(counts.measuredAssets ?? 0),
      };
    });

    if (administrativeSummaryQ.isLoading) {
      return (
        <div className="asset-page page">
          <calcite-loader label="Loading area evidence" />
        </div>
      );
    }

    if (administrativeSummaryQ.error) {
      return (
        <div className="asset-page page">
          <p className="kicker">Administrative evidence</p>
          <h1>Evidence request failed</h1>
          <calcite-notice open kind="danger" icon>
            <div slot="message">
              {administrativeSummaryQ.error instanceof Error
                ? administrativeSummaryQ.error.message
                : 'The API returned an error.'}
            </div>
          </calcite-notice>
          <calcite-button appearance="outline" kind="neutral" onClick={() => navigate('/map')}>
            Back to map
          </calcite-button>
        </div>
      );
    }

    if (!properties) {
      return (
        <div className="asset-page page">
          <p className="kicker">Administrative evidence</p>
          <h1>Area evidence not found</h1>
          <calcite-button appearance="outline" kind="neutral" onClick={() => navigate('/map')}>
            Back to map
          </calcite-button>
        </div>
      );
    }

    return (
      <div className="asset-page page">
        <p className="kicker">
          {administrativeLevel} evidence summary · {String(properties.stableCode ?? unitId)}
        </p>
        <h1>{String(properties.name ?? `${administrativeLevel} area`)}</h1>
        <p className="meta">
          {String(vulnerabilitySummary.status ?? 'not assessed')}
          {vulnerabilitySummary.periodStart
            ? ` · ${String(vulnerabilitySummary.periodStart).slice(0, 10)}`
            : ''}
          {vulnerabilitySummary.periodEnd
            ? ` to ${String(vulnerabilitySummary.periodEnd).slice(0, 10)}`
            : ''}
        </p>

        <div className="cta-row">
          <calcite-button appearance="outline" kind="neutral" onClick={() => navigate('/map?area=kano')}>
            Back to Kano map
          </calcite-button>
        </div>

        <div className="metrics">
          <div className="metric">
            <label>Assigned assets</label>
            <div className="value">{String(assetCounts.assignedAssets ?? '—')}</div>
          </div>
          <div className="metric">
            <label>Measured hazard records</label>
            <div className="value">
              {String(assetCounts.assetsWithMeasuredHazardExposure ?? '—')}
            </div>
          </div>
          <div className="metric">
            <label>Unknown exposure</label>
            <div className="value">{String(assetCounts.assetsWithUnknownExposure ?? '—')}</div>
          </div>
          <div className="metric">
            <label>Candidate exposure</label>
            <div className="value">{String(assetCounts.assetsWithCandidateExposure ?? '—')}</div>
          </div>
        </div>

        <calcite-notice open kind="warning" icon>
          <div slot="title">Composite vulnerability score withheld</div>
          <div slot="message">
            {String(
              provenance.interpretation ??
                'Area summaries report stored asset and hazard evidence. Missing evidence is not zero risk.',
            )}
          </div>
        </calcite-notice>

        <calcite-block heading="Hazard evidence" open>
          {hazardRows.length ? (
            <calcite-list label="Hazard exposure counts">
              {hazardRows.map((row) => (
                <calcite-list-item
                  key={row.hazard}
                  label={parameterLabel(row.hazard)}
                  description={`${row.exposed} exposed · ${row.unknown} unknown · ${row.measured} measured`}
                />
              ))}
            </calcite-list>
          ) : (
            <calcite-notice open kind="info" icon>
              <div slot="message">No hazard-specific counts are recorded for this area.</div>
            </calcite-notice>
          )}
        </calcite-block>

        <calcite-block heading="Assessment parameters" open>
          <calcite-list label="Area assessment parameters">
            {Object.entries({
              summaryStatus: vulnerabilitySummary.status,
              periodStart: vulnerabilitySummary.periodStart,
              periodEnd: vulnerabilitySummary.periodEnd,
              confidence: vulnerabilitySummary.confidence,
              method: provenance.method,
              assessmentRunId: provenance.assessmentRunId,
              systemClassMethod: provenance.systemClassMethod,
            })
              .filter(([, value]) => value != null && value !== '')
              .map(([key, value]) => (
              <calcite-list-item
                key={key}
                label={parameterLabel(key)}
                description={parameterValue(value)}
              />
              ))}
          </calcite-list>
          {missingEvidence.length > 0 && (
            <calcite-notice open kind="info" icon>
              <div slot="title">Missing evidence</div>
              <div slot="message">{missingEvidence.map(String).join(' · ')}</div>
            </calcite-notice>
          )}
        </calcite-block>
      </div>
    );
  }

  if (!assetId || (!asset && pilotQ.isLoading)) {
    return (
      <div className="asset-page page">
        <calcite-loader label="Loading asset record" />
      </div>
    );
  }

  if (!assetId || !asset) {
    return (
      <div className="asset-page page">
        <p className="kicker">Evidence</p>
        <h1>No asset selected</h1>
        <p className="meta">
          Open an asset from the map to review its record and evidence. Direct links are currently
          supported for the Kano pilot inventory.
        </p>
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
  const dependency = detailQ.data?.dependencies.data?.[0] ?? null;
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
      {detailQ.error && (
        <calcite-notice open kind="danger" icon>
          <div slot="title">Evidence request failed</div>
          <div slot="message">
            {detailQ.error instanceof Error ? detailQ.error.message : 'The API returned an error.'}
          </div>
        </calcite-notice>
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

        <div className="metric">
          <label>Service dependency</label>
          <div className={cn('value', toneClass(String(dependency?.status ?? 'not_assessed')))}>
            {String(dependency?.status ?? 'not assessed')}
          </div>
          <p className="note">
            {dependency?.service_type
              ? `Linked service: ${String(dependency.service_type)}`
              : 'No verified service dependency recorded'}
          </p>
        </div>
      </div>

      <calcite-notice open kind="warning" icon>
        <div slot="title">Interpretation guardrail</div>
        <div slot="message">
          Exposure is not damage, outages, or service loss. Scores are shown only when persisted
          with provenance; not assessed and withheld are distinct from zero.
        </div>
      </calcite-notice>
    </div>
  );
}
