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
      include: ['src/**/*.{ts,tsx}'],
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
        lines: 20,
        functions: 15.2,
        branches: 14.8,
        statements: 18.9,
        autoUpdate: false,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
