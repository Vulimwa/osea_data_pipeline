import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { EvidencePage } from './pages/EvidencePage';
import { MapPage } from './pages/MapPage';
import { OverviewPage } from './pages/OverviewPage';

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<MapPage />} />
          <Route path="map" element={<MapPage />} />
          <Route path="briefing" element={<OverviewPage />} />
          <Route path="evidence" element={<EvidencePage />} />
          <Route path="evidence/flood/:eventKey" element={<EvidencePage />} />
          <Route path="evidence/:assetId" element={<EvidencePage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
