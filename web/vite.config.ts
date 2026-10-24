import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Bind to all interfaces so devcontainer → VS Code port-forward → host browser
  // can reach module chunk requests. Default 'localhost' binds to IPv6 only in
  // the container, which the IPv4 forward can't route.
  server: {
    host: true,
    // The API (and the passkey session cookie) live on the FastAPI process.
    proxy: { '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
  },
});
