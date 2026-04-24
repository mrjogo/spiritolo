import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // Bind to all interfaces so devcontainer → VS Code port-forward → host browser
  // can reach module chunk requests. Default 'localhost' binds to IPv6 only in
  // the container, which the IPv4 forward can't route.
  server: { host: true },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
  },
});
