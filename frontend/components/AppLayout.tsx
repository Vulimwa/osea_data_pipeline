import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { applyTheme, getThemePreference, type Theme } from '../lib/theme';

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const path = location.pathname;
  const evidenceMatch = path.match(/^\/evidence\/([^/]+)/);
  const assetId = evidenceMatch?.[1];
  const [theme, setTheme] = useState<Theme>(getThemePreference);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <calcite-shell className="h-full">
      <calcite-navigation slot="header">
        <calcite-navigation-logo
          slot="logo"
          heading="OSEAS"
          description="Climate resilience intelligence"
          onClick={() => navigate('/map')}
        />
        <calcite-menu slot="content-start" label="Primary">
          <calcite-menu-item
            label="Overview"
            text="Risk map"
            icon-start="map"
            active={path === '/map' || path === '/' || undefined}
            onClick={() => navigate('/map')}
          />
          <calcite-menu-item
            label="Briefing"
            text="Briefing"
            icon-start="analysis"
            active={path.startsWith('/briefing') || undefined}
            onClick={() => navigate('/briefing')}
          />
          <calcite-menu-item
            label="Evidence"
            text="Evidence"
            icon-start="analysis"
            active={path.startsWith('/evidence') || undefined}
            onClick={() => navigate(assetId ? `/evidence/${assetId}` : '/evidence')}
          />
        </calcite-menu>
        <calcite-button
          slot="content-end"
          appearance="outline"
          kind="neutral"
          scale="s"
          icon-start={theme === 'light' ? 'moon' : 'sun'}
          aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
          onClick={() => setTheme((current) => (current === 'light' ? 'dark' : 'light'))}
        >
          {theme === 'light' ? 'Dark mode' : 'Light mode'}
        </calcite-button>
      </calcite-navigation>
      <div className="app-outlet">
        <Outlet context={{ theme }} />
      </div>
    </calcite-shell>
  );
}
