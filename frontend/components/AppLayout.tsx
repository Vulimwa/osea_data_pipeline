import { Outlet, useLocation, useNavigate } from 'react-router-dom';

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const path = location.pathname;
  const evidenceMatch = path.match(/^\/evidence\/([^/]+)/);
  const assetId = evidenceMatch?.[1];

  return (
    <calcite-shell className="h-full">
      <calcite-navigation slot="header">
        <calcite-navigation-logo
          slot="logo"
          heading="OSEAS"
          description="Kano plains pilot"
          onClick={() => navigate('/')}
        />
        <calcite-menu slot="content-start" label="Primary">
          <calcite-menu-item
            label="Overview"
            text="Briefing"
            icon-start="home"
            active={path === '/' || undefined}
            onClick={() => navigate('/')}
          />
          <calcite-menu-item
            label="Map"
            text="Map"
            icon-start="map"
            active={path.startsWith('/map') || undefined}
            onClick={() => navigate('/map')}
          />
          <calcite-menu-item
            label="Evidence"
            text="Evidence"
            icon-start="analysis"
            active={path.startsWith('/evidence') || undefined}
            onClick={() => navigate(assetId ? `/evidence/${assetId}` : '/evidence')}
          />
        </calcite-menu>
      </calcite-navigation>
      <div className="app-outlet">
        <Outlet />
      </div>
    </calcite-shell>
  );
}
