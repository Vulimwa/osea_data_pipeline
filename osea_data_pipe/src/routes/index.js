/** OSEAS API routes. */
'use strict';

const express = require('express');
const router = express.Router();

const oseasRoutes = require('./oseasRoutes');

router.use('/oseas', oseasRoutes);

module.exports = router;
