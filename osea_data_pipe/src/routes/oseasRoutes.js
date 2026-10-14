'use strict';

const express = require('express');
const controller = require('../controllers/oseasController');
const { supabaseBearerAuth } = require('../middleware/supabaseBearerAuth');

const router = express.Router();
router.use(supabaseBearerAuth);
router.get('/readiness', controller.getReadiness);
router.get('/catalog', controller.getCatalog);
router.get('/runs', controller.getRuns);
router.get('/runs/:id', controller.getRun);
router.get('/layers', controller.getLayers);
router.get('/layers/flood_candidate/geojson', controller.getFloodGeoJson);
router.get('/layers/flood_reference/geojson', controller.getFloodReferenceGeoJson);
router.get('/layers/hydrography/geojson', controller.getHydrographyGeoJson);
router.get('/layers/population_exposure/geojson', controller.getPopulationExposureGeoJson);
router.get('/layers/wind_resource', controller.getWindResourceManifest);
router.get('/layers/wind_resource/:product/geotiff', controller.downloadWindResource);
router.get('/layers/:layer/geojson', controller.getMapOutputGeoJson);
router.get('/assets', controller.listAssets);
router.get('/assets/:id/exposure', controller.getAssetExposure);
router.get('/assets/:id/criticality', controller.getAssetCriticality);
router.get('/assets/:id/service-dependencies', controller.getAssetServiceDependencies);
router.get('/assets/:id/vulnerability', controller.getAssetVulnerability);
router.get('/administrative/:level/:id/summary', controller.getAdminSummary);
router.get('/priorities', controller.getPriorities);

module.exports = router;
