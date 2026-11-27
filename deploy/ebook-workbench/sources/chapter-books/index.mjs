const BASE = 'http://chapter-books:8080';
const LABEL = '中文分章电子书';
const EPUB_TYPE = 'application/epub+zip';
const RELEASE_KEY = /^[a-z0-9-]{1,80}[/][a-z0-9-]{1,80}$/;

function getOrigin(config, host) {
  const base = URL.parse(config.baseUrl);
  if (!base || !['http:', 'https:'].includes(base.protocol) || base.pathname !== '/'
    || base.search || base.hash || base.username || base.password) {
    throw host.fail('error', 'Use the configured chapter-book server origin.');
  }
  return base.origin;
}

function downloadUrl(origin, guid) {
  return `${origin}/books/${guid}.epub`;
}

function validBook(book) {
  return book && typeof book.slug === 'string' && typeof book.editionId === 'string'
    && RELEASE_KEY.test(`${book.slug}/${book.editionId}`)
    && typeof book.title === 'string' && book.title.length > 0 && typeof book.author === 'string'
    && typeof book.language === 'string' && typeof book.sourceUrl === 'string'
    && Number.isSafeInteger(book.sizeBytes) && book.sizeBytes > 0;
}

export default {
  apiVersion: 1,
  version: '1.0.0',
  type: 'chapter-books',
  label: LABEL,
  defaultBaseUrl: BASE,
  baseUrlHint: 'Use the chapter-books service on the workbench container network and enable Allow private address.',
  requiresCredential: false,
  credentialKind: null,
  mediaKinds: ['ebook'],
  usesCategories: false,
  seedsBack: false,

  async search(query, config, host) {
    if (query.mediaKind !== 'ebook' || !query.title.trim() || query.limit <= 0) return [];
    const origin = getOrigin(config, host);
    const search = new URLSearchParams({ q: query.title.slice(0, 240) });
    const response = await host.fetch(`${origin}/search?${search}`, { redirect: 'manual' });
    if (!response.ok) throw host.fail('error', `The chapter EPUB catalogue is unavailable (HTTP ${response.status}).`);
    const payload = await response.json();
    if (!Array.isArray(payload.books)) throw host.fail('error', 'Invalid chapter EPUB catalogue.');
    return payload.books.filter(validBook).slice(0, query.limit).map((book) => {
      const guid = `${book.slug}/${book.editionId}`;
      return {
        guid,
        title: book.title,
        bookTitle: book.title,
        author: book.author,
        infoUrl: book.sourceUrl,
        downloadUrl: downloadUrl(origin, guid),
        format: 'epub',
        language: book.language,
        sizeBytes: book.sizeBytes,
        seeders: null,
        leechers: null,
        freeleech: true,
        primaryFileCount: 1,
      };
    });
  },

  async test(config, host) {
    const origin = getOrigin(config, host);
    const response = await host.fetch(`${origin}/healthz`, { redirect: 'manual' });
    if (response.ok && (await response.json()).status === 'ready') {
      return { success: true, indexerName: LABEL };
    }
    return { success: false, error: 'The chapter book service has no complete EPUB ready.' };
  },

  async resolveFile(release, config, host) {
    const origin = getOrigin(config, host);
    if (typeof release.guid !== 'string' || !RELEASE_KEY.test(release.guid)) {
      throw host.fail('error', 'Invalid chapter-book edition.');
    }
    const url = downloadUrl(origin, release.guid);
    if (release.downloadUrl !== url) throw host.fail('error', 'Chapter EPUB release address does not match its edition.');
    const response = await host.fetch(url, { method: 'HEAD', redirect: 'manual' });
    const size = Number(response.headers.get('Content-Length'));
    if (!response.ok || response.headers.get('Content-Type') !== EPUB_TYPE || !Number.isSafeInteger(size) || size <= 0) {
      throw host.fail('error', 'The complete chapter EPUB is unavailable for this edition.');
    }
    const name = (release.bookTitle || release.title).replace(/[\\/:*?"<>|\p{Cc}]/gu, '-').trim();
    return { url, fileName: `${name || release.guid.split('/')[0]}.epub`, sizeBytes: size, format: 'epub' };
  },
};
