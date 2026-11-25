// BookOrbit plugin API 1. Standard Ebooks' public individual-edition pages.
const BASE = 'https://standardebooks.org';
const LABEL = 'Standard Ebooks';
const BOOK_PATH = /^\/ebooks\/[a-z0-9-]+\/[a-z0-9-]+(?:\/[a-z0-9-]+)?$/;
const USER_AGENT = 'OxfordEbookWorkbench/1.0 BookOrbit';
const MAX_RESULTS = 12;

export default {
  apiVersion: 1,
  version: '1.0.0',
  type: 'standard-ebooks',
  label: LABEL,
  defaultBaseUrl: BASE,
  baseUrlHint: 'The public Standard Ebooks origin.',
  requiresCredential: false,
  credentialKind: null,
  mediaKinds: ['ebook'],
  usesCategories: false,
  seedsBack: false,

  async search(query, config, host) {
    if (query.mediaKind !== 'ebook' || query.limit <= 0) return [];
    const title = host.buildSearchText(query).trim().slice(0, 150);
    if (!title || /\p{Script=Han}/u.test(title)) return [];
    return catalogue(title, query.limit, config, host);
  },

  async test(config, host) {
    const books = await catalogue('Pride and Prejudice Jane Austen', 1, config, host);
    return books.length
      ? { success: true, indexerName: LABEL }
      : { success: false, error: 'No Standard Ebooks edition was returned for the test title.' };
  },

  async resolveFile(release, config, host) {
    verifyBase(config, host);
    const path = release.guid;
    if (!BOOK_PATH.test(path)) throw host.fail('error', 'The edition path is not valid for Standard Ebooks.');
    const edition = await page(BASE + path, host);
    const license = [...edition.matchAll(/<meta\b([^>]+)>/g)].map((m) => attributes(m[1]))
      .find((tag) => tag.property === 'schema:license')?.content;
    if (license !== 'https://creativecommons.org/publicdomain/zero/1.0/') {
      throw host.fail('error', 'The edition does not state the expected public-domain dedication.');
    }

    const link = [...edition.matchAll(/<a\b([^>]+)>/g)].map((m) => attributes(m[1]))
      .find((tag) => tag.property === 'schema:contentUrl' && tag.class?.split(/\s+/).includes('epub')
        && compatibleEpub(tag.href, path));
    if (!link) throw host.fail('error', 'This edition has no compatible EPUB link.');

    const confirmation = await page(BASE + link.href, host);
    const refresh = [...confirmation.matchAll(/<meta\b([^>]+)>/g)].map((m) => attributes(m[1]))
      .find((tag) => tag['http-equiv']?.toLowerCase() === 'refresh')?.content;
    const target = refresh?.match(/\burl\s*=\s*(\S+)\s*$/i)?.[1];
    if (!target) throw host.fail('error', 'Standard Ebooks did not publish a final EPUB download link.');
    const direct = new URL(target, BASE);
    if (direct.origin !== BASE || direct.username || direct.password || direct.pathname !== link.href
        || direct.search !== '?source=download' || direct.hash) {
      throw host.fail('error', 'Standard Ebooks returned an unexpected download target.');
    }
    return {
      url: direct.href,
      fileName: direct.pathname.split('/').at(-1),
      sizeBytes: null,
      format: 'epub',
    };
  },
};

async function catalogue(title, limit, config, host) {
  verifyBase(config, host);
  const url = new URL('/ebooks', BASE);
  url.searchParams.set('query', title);
  const body = await page(url.href, host);
  const found = [];
  // The site's XHTML emits a flat list of schema:Book records, each with the work and byline.
  for (const match of body.matchAll(/<li\b([^>]*\btypeof="schema:Book"[^>]*)>([\s\S]*?)<\/li>/g)) {
    const path = attributes(match[1]).about;
    if (!path || !BOOK_PATH.test(path)) continue;
    const names = [...match[2].matchAll(/<span\b[^>]*\bproperty="schema:name"[^>]*>([\s\S]*?)<\/span>/g)]
      .map((node) => decodeEntities(node[1].replace(/<[^>]*>/g, '')).replace(/\s+/g, ' ').trim()).filter(Boolean);
    const [bookTitle, ...authors] = names;
    if (!bookTitle) continue;
    found.push({
      guid: path,
      title: bookTitle,
      bookTitle,
      author: [...new Set(authors)].join(', ') || undefined,
      infoUrl: BASE + path,
      format: 'epub',
      language: 'en',
      sizeBytes: null,
      seeders: null,
      leechers: null,
      freeleech: true,
      primaryFileCount: 1,
    });
    if (found.length >= Math.min(limit, MAX_RESULTS)) break;
  }
  return found;
}

function verifyBase(config, host) {
  if (config.baseUrl.replace(/\/$/, '') !== BASE) {
    throw host.fail('error', 'Use the public Standard Ebooks origin for this source.');
  }
}

function compatibleEpub(href, edition) {
  const prefix = edition + '/downloads/';
  if (!href?.startsWith(prefix)) return false;
  const name = href.slice(prefix.length);
  return /^[a-z0-9_-]+\.epub$/.test(name) && !name.endsWith('_advanced.epub');
}

async function page(url, host) {
  const response = await host.fetch(url, {
    headers: { Accept: 'application/xhtml+xml, text/html', 'User-Agent': USER_AGENT },
    redirect: 'manual',
  });
  if (response.status === 429 || response.headers.has('Retry-After')) {
    throw host.fail('throttled', 'Standard Ebooks requested a pause. Try the source later.');
  }
  if (response.status === 401 || response.status === 403) {
    throw host.fail('unauthorized', `Standard Ebooks refused the request (HTTP ${response.status}).`);
  }
  if (!response.ok) throw host.fail('error', `Standard Ebooks returned HTTP ${response.status}.`);
  return response.text();
}

function attributes(source) {
  return Object.fromEntries([...source.matchAll(/([\w:-]+)\s*=\s*"([^"]*)"/g)]
    .map((match) => [match[1], decodeEntities(match[2])]));
}

function decodeEntities(value) {
  const named = { amp: '&', lt: '<', gt: '>', apos: "'", quot: '"', nbsp: ' ' };
  return value.replace(/&(#x[\da-f]+|#\d+|amp|lt|gt|apos|quot|nbsp);/gi, (entity, code) => {
    if (!code.startsWith('#')) return named[code.toLowerCase()] ?? entity;
    const point = code[1].toLowerCase() === 'x' ? Number.parseInt(code.slice(2), 16) : Number(code.slice(1));
    return point > 0 && point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff)
      ? String.fromCodePoint(point) : entity;
  });
}
