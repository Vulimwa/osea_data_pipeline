import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'motion/react';
import { AssetMap } from './components/AssetMap';
import { DetailPanel } from './components/DetailPanel';
import {
  AssetFeature,
  ExposureRow,
  PILOT_DATASET,
  Readiness,
  VulnerabilityRow,
  fetchAssetExposure,
  fetchAssetVulnerability,
  fetchAssetsInBbox,
  fetchReadiness,
} from './lib/api';

export default function App() {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [assets, setAssets] = useState<AssetFeature[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(true);
  const [pilotOnly, setPilotOnly] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exposure, setExposure] = useState<ExposureRow[] | null>(null);
  const [vulnerability, setVulnerability] = useState<VulnerabilityRow | null>(null);
  const [detailStatus, setDetailStatus] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoadingList(true);
      setError(null);
      try {
        const [ready, list] = await Promise.all([fetchReadiness(), fetchAssetsInBbox(500)]);
        if (cancelled) return;
        setReadiness(ready);
        setAssets(list);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoadingList(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setExposure(null);
      setVulnerability(null);
      setDetailStatus(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoadingDetail(true);
      try {
        const [exp, vuln] = await Promise.all([
          fetchAssetExposure(selectedId),
          fetchAssetVulnerability(selectedId),
        ]);
        if (cancelled) return;
        setExposure(exp.data ?? []);
        setVulnerability(vuln.data?.[0] ?? null);
        setDetailStatus(vuln.status || exp.status || null);
      } catch (err) {
        if (!cancelled) {
          setDetailStatus(err instanceof Error ? err.message : String(err));
          setExposure(null);
          setVulnerability(null);
        }
      } finally {
        if (!cancelled) setLoadingDetail(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const selected = useMemo(
    () => assets.find((a) => a.id === selectedId) ?? null,
    [assets, selectedId],
  );

  const pilotCount = useMemo(
    () => assets.filter((a) => a.properties.sourceDataset === PILOT_DATASET).length,
    [assets],
  );

  const onSelect = useCallback((id: string) => setSelectedId(id), []);

  const readyLabel = readiness?.apiReadyForIntegration
    ? 'API ready'
    : readiness
      ? `API ${readiness.status || 'blocked'}`
      : loadingList
        ? 'Connecting…'
        : 'API unknown';

  return (
    <div className="relative h-full min-h-0 overflow-hidden">
      <AssetMap
        assets={assets}
        selectedId={selectedId}
        onSelect={onSelect}
        pilotOnly={pilotOnly}
      />

      <motion.header
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
        className="pointer-events-none absolute inset-x-0 top-0 z-10 p-4 md:p-6"
      >
        <div className="pointer-events-auto max-w-xl border border-[var(--line)] bg-[var(--panel)] px-4 py-3 backdrop-blur-md md:px-5 md:py-4">
          <p className="brand text-2xl tracking-tight md:text-3xl">OSEAS</p>
          <p className="mt-1 text-sm text-[var(--mist)]/75 md:text-base">
            Kano plains flood pilot — energy assets on Lake Victoria’s shore.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[var(--mist)]/55">
            <span>{readyLabel}</span>
            <span aria-hidden>·</span>
            <span>
              {loadingList
                ? 'Loading assets…'
                : `${pilotCount} pilot · ${assets.length} in bbox`}
            </span>
            <label className="ml-auto flex cursor-pointer items-center gap-2 text-[var(--mist)]/70">
              <input
                type="checkbox"
                checked={pilotOnly}
                onChange={(e) => setPilotOnly(e.target.checked)}
                className="accent-[var(--flood)]"
              />
              Pilot only
            </label>
          </div>
          {error && (
            <p className="mt-3 text-sm text-[var(--flood-soft)]">
              {error}. Is the API on :3000? Use pooler DATABASE_URL.
            </p>
          )}
        </div>
      </motion.header>

      <motion.div
        initial={{ opacity: 0, x: 24 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ duration: 0.6, delay: 0.08, ease: [0.22, 1, 0.36, 1] }}
      >
        <DetailPanel
          asset={selected}
          exposure={exposure}
          vulnerability={vulnerability}
          detailStatus={detailStatus}
          loading={loadingDetail}
          onClose={() => setSelectedId(null)}
        />
      </motion.div>
    </div>
  );
}
