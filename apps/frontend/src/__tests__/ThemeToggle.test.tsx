import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ThemeToggle } from '../components/ThemeToggle'
import { toggleTheme } from '@/lib/theme'
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
  it('toggles theme on click', () => {
    render(<ThemeToggle />)
    const button = screen.getByRole('button', { name: /switch to dark mode/i })
    fireEvent.click(button)
    expect(toggleTheme).toHaveBeenCalled()
  })
})
