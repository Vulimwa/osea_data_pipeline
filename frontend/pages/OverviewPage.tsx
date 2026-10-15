import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { fetchDatasetCatalog, fetchReadiness } from '../lib/api';

function formatStatus(status: unknown) {
  if (status == null || status === '') return 'Not assessed';
  return String(status).replaceAll('_', ' ');
}

export function OverviewPage() {
  const navigate = useNavigate();
  const readinessQ = useQuery({ queryKey: ['readiness'], queryFn: fetchReadiness, retry: 0 });
  const catalogQ = useQuery({
    queryKey: ['dataset-catalog'],
    queryFn: fetchDatasetCatalog,
    retry: 0,
  });
  const checks = readinessQ.data?.checks;
  const prithvi = checks?.prithviNational as Record<string, unknown> | undefined;

  return (
    <main className="briefing page">
      <calcite-chip label="OSEAS climate and power" scale="s" kind="brand" icon="analysis">
        OSEAS · CLIMATE × POWER
      </calcite-chip>
      <h1>See where climate risk meets power infrastructure.</h1>
      <p className="lede">
        Map hazards against energy assets, inspect evidence, and focus resilience action. Missing
        evidence stays unknown—not low risk.
      </p>
      <div className="cta-row">
        <calcite-button kind="brand" icon-start="map" onClick={() => navigate('/map')}>
          Explore the risk map
        </calcite-button>
        <calcite-button
          appearance="outline"
          kind="neutral"
          icon-start="map-pin"
          onClick={() => navigate('/map?area=kano')}
        >
          Open Kano demo
        </calcite-button>
      </div>

      {(readinessQ.error || catalogQ.error) && (
        <calcite-notice open kind="danger" icon>
          <div slot="title">Live data could not be loaded</div>
          <div slot="message">
            {readinessQ.error instanceof Error
              ? readinessQ.error.message
              : catalogQ.error instanceof Error
                ? catalogQ.error.message
                : 'Check API connectivity and account access.'}
          </div>
        </calcite-notice>
      )}

      <div className="briefing-grid">
        <calcite-panel heading="The challenge">
          <p className="briefing-panel-copy">
            See climate signals alongside the power assets and communities they may affect.
          </p>
        </calcite-panel>
        <calcite-panel heading="The decision workflow">
          <calcite-list label="Decision workflow">
            <calcite-list-item label="Locate" description="Map assets and hazards." />
            <calcite-list-item label="Assess" description="Review evidence and gaps." />
            <calcite-list-item label="Prioritize" description="Focus resilience action." />
          </calcite-list>
        </calcite-panel>
      </div>

      <calcite-panel heading="Evidence status" className="briefing-status-panel">
        <div className="briefing-status-grid">
          <div>
            <span>API readiness</span>
            <strong>{readinessQ.isLoading ? 'Connecting…' : formatStatus(readinessQ.data?.status)}</strong>
          </div>
          <div>
            <span>National Prithvi run</span>
            <strong>{formatStatus(prithvi?.status)}</strong>
          </div>
          <div>
            <span>County summaries</span>
            <strong>{Number(prithvi?.countySummaries ?? 0).toLocaleString()}</strong>
          </div>
          <div>
            <span>Ward summaries</span>
            <strong>{Number(prithvi?.wardSummaries ?? 0).toLocaleString()}</strong>
          </div>
          <div>
            <span>Registered source datasets</span>
            <strong>{Number(catalogQ.data?.count ?? catalogQ.data?.data?.length ?? 0).toLocaleString()}</strong>
          </div>
        </div>
      </calcite-panel>

      <calcite-notice open kind="warning" icon>
        <div slot="message">
          Candidate signals are not confirmed events. Missing evidence is unknown, not zero risk.
        </div>
      </calcite-notice>
    </main>
  );
}
