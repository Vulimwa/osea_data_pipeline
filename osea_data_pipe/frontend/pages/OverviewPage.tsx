import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchPilotAssets, fetchReadiness, withTimeout } from '../lib/api';

export function OverviewPage() {
  const navigate = useNavigate();

  const readinessQ = useQuery({
    queryKey: ['readiness'],
    queryFn: () =>
      withTimeout(fetchReadiness(), 8000, { status: 'timeout', apiReadyForIntegration: false }),
    retry: 0,
  });

  const pilotQ = useQuery({
    queryKey: ['assets-pilot'],
    queryFn: fetchPilotAssets,
    retry: 1,
  });

  const apiReady = readinessQ.data?.apiReadyForIntegration;
  const pilotCount = pilotQ.data?.length;

  const openKolwa = () => {
    const kolwa = (pilotQ.data ?? []).find((a) =>
      (a.properties.name || '').toLowerCase().includes('kolwa'),
    );
    if (kolwa) navigate(`/evidence/${kolwa.id}`);
    else navigate('/map');
  };

  return (
    <div className="briefing page">
      <p className="brand">OSEAS</p>
      <h1>Kano plains flood pilot</h1>
      <p className="lede">
        Nyando basin energy assets · flood screening evidence for 2011–2020. Not an engineering
        certificate.
      </p>

      <div className="stat-row">
        <div className="stat">
          API
          <strong>
            {apiReady == null ? '…' : apiReady ? 'Ready' : readinessQ.data?.status || 'Blocked'}
          </strong>
        </div>
        <div className="stat">
          Pilot assets
          <strong>{pilotCount == null ? '…' : pilotCount}</strong>
        </div>
        <div className="stat">
          Period
          <strong>2011–2020</strong>
        </div>
        <div className="stat">
          Dataset
          <strong>osm_kano_pilot</strong>
        </div>
      </div>

      <div className="cta-row">
        <calcite-button kind="brand" onClick={() => navigate('/map')}>
          Open map
        </calcite-button>
        <calcite-button appearance="outline" kind="neutral" onClick={openKolwa}>
          Kolwa East evidence
        </calcite-button>
      </div>

      <ul className="brief-list">
        <li>
          <strong>Map</strong>
          <span>Locate pilot assets in the Kano bbox; find Kolwa / substations.</span>
        </li>
        <li>
          <strong>Evidence</strong>
          <span>Flood exposure + vulnerability per asset, with method and period.</span>
        </li>
        <li>
          <strong>Gaps</strong>
          <span>Criticality, heat, wildfire stay not assessed until evidence exists.</span>
        </li>
      </ul>

      <p className="honesty">
        Honesty rule: missing evidence is never drawn as zero risk. Grey means unknown, not safe.
      </p>
    </div>
  );
}
