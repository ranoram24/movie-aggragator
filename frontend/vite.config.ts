import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // 5173 is the port reserved for the frontend; 8000 is deliberately left
    // alone and the backend runs on 8010.
    port: 5173,
    strictPort: true,
  },
});
