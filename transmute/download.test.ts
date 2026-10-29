import { afterEach, expect, it, vi } from 'vitest'
import { downloadFile } from './download'

vi.mock('./api', () => ({ authFetch: (...args: Parameters<typeof fetch>) => fetch(...args) }))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it.each([0, 32, 2])('preserves the displayed Unicode filename with chunk size %i', async chunkSize => {
  const filename = 'Reading, 100% -- Reader’s Book.epub'
  const headers = {
    'content-disposition': "attachment; filename*=utf-8''Reading%2C%20100%25%20--%20Reader%E2%80%99s%20Book.epub",
    'content-length': '4',
  }
  vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
    if (init?.method === 'HEAD') return new Response(null, { headers })
    if (init?.headers?.Range) return new Response('ab', { status: 206 })
    return new Response('abcd', { headers })
  }))
  Object.defineProperty(window.URL, 'createObjectURL', { configurable: true, value: vi.fn(() => 'blob:test') })
  Object.defineProperty(window.URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
  let savedName = ''
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    savedName = this.download
  })

  await downloadFile('/api/files/fixture', filename, chunkSize)

  expect(savedName).toBe(filename)
})
