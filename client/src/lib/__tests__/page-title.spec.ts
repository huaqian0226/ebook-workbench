import { describe, expect, it } from 'vitest'
import { APP_TITLE, formatPageTitle } from '@/lib/page-title'

describe('formatPageTitle', () => {
  it('returns app title when leaf title is empty', () => {
    expect(formatPageTitle('')).toBe(APP_TITLE)
    expect(formatPageTitle('   ')).toBe(APP_TITLE)
    expect(formatPageTitle(null)).toBe(APP_TITLE)
    expect(formatPageTitle(undefined)).toBe(APP_TITLE)
  })

  it('formats non-empty leaf title', () => {
    expect(formatPageTitle('Authors')).toBe('Authors · 电子书工作台')
    expect(formatPageTitle('  Dashboard  ')).toBe('Dashboard · 电子书工作台')
  })
})
