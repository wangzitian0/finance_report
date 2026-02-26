import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'happy-dom',
    setupFiles: ['./vitest.setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html', 'lcov'],
      // Blacklist approach: exclude test/config files, everything else counts as code
      exclude: [
        'node_modules/',
        '.next/',
        'coverage/',
        '**/tests/**',
        '**/__tests__/**',
        '**/*.test.ts',
        '**/*.test.tsx',
        '**/*.spec.ts',
        '**/*.spec.tsx',
        '**/vitest.setup.ts',
        '**/*.config.*',
        '**/types/**',
      ],
      thresholds: {
        lines: 50,
        functions: 60,
        branches: 45,
        statements: 50,
        autoUpdate: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
