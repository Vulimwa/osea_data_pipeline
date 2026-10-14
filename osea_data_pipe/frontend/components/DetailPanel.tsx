import type { AssetFeature, ExposureRow, VulnerabilityRow } from '../lib/api';
import { PILOT_DATASET } from '../lib/api';

type Props = {
  asset: AssetFeature | null;
  exposure: ExposureRow[] | null;
  vulnerability: VulnerabilityRow | null;
  detailStatus: string | null;
  loading: boolean;
  onClose: () => void;
};

function classTone(label: string | null | undefined): string {
  const v = (label || '').toLowerCase();
  if (v === 'unknown' || v === 'not_assessed') return 'text-[var(--unknown)]';
  if (v === 'low') return 'text-[var(--safe)]';
  if (v === 'moderate') return 'text-[var(--flood-soft)]';
  if (v === 'high' || v === 'very_high') return 'text-[var(--flood)]';
  return 'text-[var(--mist)]';
}

export function DetailPanel({
  asset,
  exposure,
  vulnerability,
  detailStatus,
  loading,
  onClose,
}: Props) {
  if (!asset) {
    return (
      <aside className="pointer-events-none absolute inset-x-0 bottom-0 z-10 p-4 md:inset-y-0 md:left-auto md:right-0 md:w-[22rem] md:p-5">
        <div className="pointer-events-auto border border-[var(--line)] bg-[var(--panel)] px-4 py-4 backdrop-blur-md md:h-full md:px-5 md:py-6">
          <p className="brand text-lg text-[var(--mist)]">Select an asset</p>
          <p className="mt-2 text-sm leading-relaxed text-[var(--mist)]/70">
            Orange markers are the Kano plains OSM pilot. Teal markers are other inventory
            assets in the same box. Unknown is never drawn as zero risk.
          </p>
        </div>
      </aside>
    );
  }

  const flood = exposure?.find((row) => row.hazard_type === 'flood');
  const heat = exposure?.find((row) => row.hazard_type === 'heat');
  const wildfire = exposure?.find((row) => row.hazard_type === 'wildfire');
  const floodScore = flood?.provenance?.exposure;
  const isPilot = asset.properties.sourceDataset === PILOT_DATASET;

  return (
    <aside className="pointer-events-none absolute inset-x-0 bottom-0 z-10 max-h-[55vh] overflow-auto p-4 md:inset-y-0 md:left-auto md:right-0 md:max-h-none md:w-[22rem] md:p-5">
      <div className="pointer-events-auto border border-[var(--line)] bg-[var(--panel)] px-4 py-4 backdrop-blur-md md:min-h-full md:px-5 md:py-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-[0.7rem] uppercase tracking-[0.16em] text-[var(--mist)]/50">
              {isPilot ? 'Pilot · osm_kano_pilot' : asset.properties.sourceDataset || 'inventory'}
            </p>
            <h2 className="brand mt-1 text-2xl leading-tight">
              {asset.properties.name || 'Unnamed asset'}
            </h2>
            <p className="mt-1 text-sm text-[var(--mist)]/65">{asset.properties.assetType}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-[var(--mist)]/55 transition hover:text-[var(--mist)]"
          >
            Close
          </button>
        </div>

        {loading && (
          <p className="mt-6 text-sm text-[var(--mist)]/55">Loading exposure…</p>
        )}
        {!loading && detailStatus && (
          <p className="mt-6 text-xs uppercase tracking-[0.14em] text-[var(--mist)]/45">
            Detail status · {detailStatus}
          </p>
        )}

        <dl className="mt-5 space-y-4 text-sm">
          <div>
            <dt className="text-[var(--mist)]/45">Flood exposure</dt>
            <dd className="mt-1 text-lg tabular-nums">
              {flood == null ? (
                <span className={classTone('unknown')}>not assessed</span>
              ) : floodScore == null || Number.isNaN(Number(floodScore)) ? (
                <span className={classTone(flood.exposure_status)}>{flood.exposure_status}</span>
              ) : (
                <>
                  <span className="text-[var(--flood-soft)]">{Number(floodScore).toFixed(3)}</span>
                  <span className="ml-2 text-[var(--mist)]/50">{flood.exposure_status}</span>
                </>
              )}
            </dd>
            {flood?.provenance?.observed && (
              <dd className="mt-1 text-xs text-[var(--mist)]/45">
                observed {flood.provenance.observed}
                {flood.provenance.method ? ` · ${flood.provenance.method}` : ''}
              </dd>
            )}
          </div>

          <div>
            <dt className="text-[var(--mist)]/45">Vulnerability</dt>
            <dd className={`mt-1 text-lg tabular-nums ${classTone(vulnerability?.vulnerability_class)}`}>
              {vulnerability?.score == null ? (
                vulnerability?.vulnerability_class || vulnerability?.status || 'not assessed'
              ) : (
                <>
                  {Number(vulnerability.score).toFixed(3)}
                  <span className="ml-2 text-base">
                    {vulnerability.vulnerability_class || '—'}
                  </span>
                </>
              )}
            </dd>
            {vulnerability?.method && (
              <dd className="mt-1 text-xs text-[var(--mist)]/45">{vulnerability.method}</dd>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-4">
            <div>
              <dt className="text-[var(--mist)]/45">Heat</dt>
              <dd className={`mt-1 ${classTone(heat?.exposure_status || 'unknown')}`}>
                {heat?.exposure_status || 'not assessed'}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--mist)]/45">Wildfire</dt>
              <dd className={`mt-1 ${classTone(wildfire?.exposure_status || 'unknown')}`}>
                {wildfire?.exposure_status || 'not assessed'}
              </dd>
            </div>
          </div>
        </dl>
      </div>
    </aside>
  );
}
