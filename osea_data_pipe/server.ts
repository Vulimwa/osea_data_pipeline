import app from './src/app.js';
import config from './src/config/index.js';
import db from './src/repositories/db.js';
import logger from './src/utils/logger.js';

const server = app.listen(config.PORT, config.HOST, () => {
  logger.info('OSEAS API server initialized successfully', {
    port: config.PORT,
    host: config.HOST,
    env: config.NODE_ENV,
    version: config.PROCESSING_VERSION,
  });
  console.log(`OSEAS API running on http://${config.HOST}:${config.PORT}`);
});

let shuttingDown = false;
async function shutdown(signal: string): Promise<void> {
  if (shuttingDown) return;
  shuttingDown = true;
  logger.info(`Received ${signal}; closing OSEAS API`);
  server.close(async () => {
    try {
      await db.closePool();
      process.exit(0);
    } catch (error) {
      logger.error('Failed to close database pool', { error });
      process.exit(1);
    }
  });
  setTimeout(() => process.exit(1), 10_000).unref();
}

process.on('SIGTERM', () => void shutdown('SIGTERM'));
process.on('SIGINT', () => void shutdown('SIGINT'));
