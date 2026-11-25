// BookOrbit plugin API 1. Human-initiated searches of public-domain Chinese book scans.
const COMMONS = 'https://commons.wikimedia.org';
const WIKIPEDIA_ZH = 'https://zh.wikipedia.org';
const UPLOAD = 'https://upload.wikimedia.org';
const COLLECTION = 'Scans from the Taiwan eBook database, National Central Library';
const LABEL = 'Wikimedia Commons · Chinese books';
const BOOK_LIMIT = 20;

export default {
  apiVersion: 1,
  version: '1.0.0',
  type: 'wikimedia-commons-books',
  label: LABEL,
  defaultBaseUrl: COMMONS,
  baseUrlHint: 'The public Wikimedia Commons origin.',
  requiresCredential: false,
  credentialKind: null,
  mediaKinds: ['ebook'],
  usesCategories: false,
  seedsBack: false,
  settingsFields: [{
    key: 'operatorContact',
    type: 'string',
    label: 'Wikimedia operator contact',
    hint: 'Optional for personal lookups. Provide an operator email, website or Wiki user for automated use.',
  }],

  async search(query, config, host) {
    if (query.mediaKind !== 'ebook' || query.limit <= 0) return [];
    const title = query.title.normalize('NFKC')
      .replace(/[^\p{L}\p{N}\p{M}\s]/gu, ' ').replace(/\s+/g, ' ').trim().slice(0, 120);
    if (!/\p{Script=Han}/u.test(title)) return [];
    return searchBooks(title, query.limit, config, host);
  },

  async test(config, host) {
    const books = await searchBooks('唐诗三百首', 5, config, host);
    return books.length
      ? { success: true, indexerName: LABEL }
      : { success: false, error: 'No public-domain Chinese scan was returned for the test title.' };
  },

  async resolveFile(release, _config, host) {
    const url = originalPdf(release.downloadUrl);
    if (!url) throw host.fail('error', 'The release has no Wikimedia Commons original PDF.');
    return {
      url,
      fileName: decodeURIComponent(new URL(url).pathname.split('/').at(-1)),
      format: 'pdf',
      sizeBytes: release.sizeBytes,
    };
  },
};

async function searchBooks(title, limit, config, host) {
  if (config.baseUrl.replace(/\/$/, '') !== COMMONS) {
    throw host.fail('error', 'Use the public Wikimedia Commons origin for this source.');
  }
  const query = await toTraditional(title, config, host);
  const result = await api(COMMONS, {
    action: 'query',
    generator: 'search',
    gsrnamespace: '6',
    gsrlimit: String(BOOK_LIMIT),
    gsrsearch: `intitle:"${query}" filemime:pdf incategory:"${COLLECTION}"`,
    prop: 'imageinfo|revisions',
    iiprop: 'url|mime|size|extmetadata',
    iiextmetadatafilter: 'Copyrighted|LicenseShortName',
    rvprop: 'content',
    rvslots: 'main',
  }, config, host);

  const pages = result.query?.pages ?? [];
  const matches = [];
  for (const page of pages) {
    const book = releasedBook(page);
    if (book) matches.push(book);
  }
  return matches.sort((a, b) => rank(b, query) - rank(a, query)).slice(0, Math.min(limit, BOOK_LIMIT));
}

function rank(book, query) {
  return Number(book.bookTitle.replace(/\s+/g, '') === query.replace(/\s+/g, ''));
}

async function toTraditional(title, config, host) {
  const result = await api(WIKIPEDIA_ZH, {
    action: 'parse',
    text: title,
    contentmodel: 'wikitext',
    prop: 'text',
    variant: 'zh-hant',
    disablelimitreport: '1',
  }, config, host);
  const converted = result.parse?.text?.match(/<p>([^<]*)<\/p>/)?.[1]?.trim();
  if (!converted || !/^[\p{L}\p{N}\p{M}\s]+$/u.test(converted)) {
    throw host.fail('error', 'Wikimedia did not return a usable Chinese title variant.');
  }
  return converted;
}

async function api(origin, params, config, host) {
  const url = new URL('/w/api.php', origin);
  url.search = new URLSearchParams({ format: 'json', formatversion: '2', maxlag: '5', ...params });
  const contact = config.settings?.operatorContact;
  const byline = typeof contact === 'string' && /^[ -~]{1,200}$/.test(contact) ? ` (${contact})` : '';
  const response = await host.fetch(url.href, {
    headers: { Accept: 'application/json', 'User-Agent': `OxfordEbookWorkbench/1.0${byline} BookOrbit` },
    redirect: 'manual',
  });
  if (response.status === 429 || response.headers.has('Retry-After')) {
    throw host.fail('throttled', 'Wikimedia requested a pause. Try the source later.');
  }
  if (response.status === 401 || response.status === 403) {
    throw host.fail('unauthorized', `Wikimedia refused the request (HTTP ${response.status}).`);
  }
  if (!response.ok) throw host.fail('error', `Wikimedia returned HTTP ${response.status}.`);
  const data = await response.json();
  if (data.error?.code === 'maxlag' || data.error?.code === 'ratelimited') {
    throw host.fail('throttled', 'Wikimedia requested a pause. Try the source later.');
  }
  if (data.error) throw host.fail('error', 'Wikimedia reported a search error.');
  return data;
}

function releasedBook(page) {
  const info = page.imageinfo?.[0];
  const license = info?.extmetadata?.LicenseShortName?.value;
  const copyrighted = info?.extmetadata?.Copyrighted?.value;
  if (info?.mime !== 'application/pdf' || license !== 'Public domain' || copyrighted !== 'False') return null;
  const downloadUrl = originalPdf(info.url);
  if (!downloadUrl || !Number.isSafeInteger(page.pageid)) return null;
  const wiki = page.revisions?.[0]?.slots?.main?.content;
  if (typeof wiki !== 'string' || !/\{\{Book\b/i.test(wiki)) return null;
  const field = (name) => wiki.match(new RegExp(`^[ \\t]*\\|[ \\t]*${name}[ \\t]*=[ \\t]*([^\\n|{}]+)`, 'mi'))?.[1]
    ?.trim().replace(/^\[([^\[\]]+)\]$/, '$1');
  const bookTitle = field('Title');
  if (!bookTitle || !/^(zh|zho|chi|chinese)$/i.test(field('Language') ?? '')) return null;
  const scanId = /^([A-Z]+-[\d-]+)_/.exec(new URL(downloadUrl).pathname.split('/').at(-1))?.[1];
  const edition = [field('Publisher'), field('Edition'), field('Volume'), field('Publication date'), scanId].filter(Boolean);
  return {
    guid: String(page.pageid),
    title: [bookTitle, ...edition].join(' · '),
    bookTitle,
    author: field('Author'),
    infoUrl: `${COMMONS}/wiki/Special:Redirect/page/${page.pageid}`,
    downloadUrl,
    format: 'pdf',
    language: 'zh',
    sizeBytes: Number.isSafeInteger(info.size) && info.size > 0 ? info.size : null,
    seeders: null,
    leechers: null,
    freeleech: true,
    primaryFileCount: 1,
  };
}

function originalPdf(value) {
  if (typeof value !== 'string') return null;
  try {
    const url = new URL(value);
    const path = /^\/wikipedia\/commons\/[0-9a-f]\/[0-9a-f]{2}\/([^/]+\.pdf)$/i.exec(url.pathname);
    if (url.origin !== UPLOAD || url.username || url.password || !path) return null;
    const fileName = decodeURIComponent(path[1]);
    if (/[\\/\u0000-\u001f\u007f]/.test(fileName)) return null;
    return url.origin + url.pathname;
  } catch {
    return null;
  }
}
