import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThemeToggle } from '../components/ThemeToggle'

vi.mock('@/lib/theme', () => ({
  getTheme: vi.fn(() => 'light'),
  toggleTheme: vi.fn(() => 'dark'),
  initTheme: vi.fn(),
}))

describe('ThemeToggle', () => {
  it('renders a button', () => {
    render(<ThemeToggle />)
    const button = screen.getByRole('button')
    expect(button).toBeDefined()
  })

  it('shows light mode icon initially', () => {
    render(<ThemeToggle />)
    const button = screen.getByRole('button')
    expect(button).toHaveAttribute('aria-label', 'Switch to dark mode')
  })
})
