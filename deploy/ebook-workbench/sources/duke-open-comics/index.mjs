// BookOrbit plugin API 1. Curated official publications from Duke Law's CSPD.
const BASE = 'https://cspd.law.duke.edu';
const LABEL = 'Duke Law CSPD Comics';
const RELEASES = [
  {
    guid: 'bound-by-law-image-archive',
    title: 'Tales from the Public Domain: Bound by Law?',
    author: 'Keith Aoki, James Boyle, Jennifer Jenkins',
    infoUrl: BASE + '/comics/digital/',
    downloadUrl: 'https://law.duke.edu/centers/cspd/comics/digital/boundbylaw_jpgs.zip',
    fileName: 'Bound by Law.cbz',
    format: 'cbz',
  },
  {
    guid: 'theft-a-history-of-music-pdf',
    title: 'Theft! A History of Music',
    author: 'James Boyle, Jennifer Jenkins, Keith Aoki',
    infoUrl: BASE + '/musiccomic/download/',
    downloadUrl: 'https://law.duke.edu/sites/default/files/centers/cspd/musiccomic/Theft.pdf',
    fileName: 'Theft - A History of Music.pdf',
    format: 'pdf',
  },
];

export default {
  apiVersion: 1,
  version: '1.0.0',
  type: 'duke-open-comics',
  label: LABEL,
  defaultBaseUrl: BASE,
  baseUrlHint: 'Duke Law Center for the Study of the Public Domain.',
  requiresCredential: false,
  credentialKind: null,
  mediaKinds: ['ebook'], // BookOrbit 3.10.0 includes comics in this request kind.
  usesCategories: false,
  seedsBack: false,

  async search(query, config, host) {
    verifyBase(config, host);
    if (query.mediaKind !== 'ebook' || query.limit <= 0) return [];
    const wanted = tokens(query.title.slice(0, 240));
    if (!wanted.length) return [];
    return RELEASES.filter((release) => {
      const available = tokens(release.title);
      return wanted.every((token) => available.includes(token));
    }).slice(0, query.limit).map(({ guid, title, author, infoUrl, downloadUrl, format }) => ({
      guid,
      title,
      bookTitle: title,
      author,
      infoUrl,
      downloadUrl,
      format,
      language: 'en',
      sizeBytes: null,
      seeders: null,
      leechers: null,
      freeleech: true,
      primaryFileCount: 1,
    }));
  },

  async test(config, host) {
    verifyBase(config, host);
    const archive = RELEASES[0];
    const response = await host.fetch(archive.downloadUrl, {
      method: 'HEAD',
      headers: { 'User-Agent': 'OxfordEbookWorkbench/1.0 BookOrbit' },
      redirect: 'manual',
    });
    if (response.status === 429 || response.headers.has('Retry-After')) {
      throw host.fail('throttled', 'Duke Law requested a pause. Try the source later.');
    }
    if (response.ok && response.headers.get('Content-Type')?.split(';')[0] === 'application/zip') {
      return { success: true, indexerName: LABEL };
    }
    return { success: false, error: `Duke Law did not answer with the published comic archive (HTTP ${response.status}).` };
  },

  async resolveFile(release, config, host) {
    verifyBase(config, host);
    const published = RELEASES.find((known) => known.guid === release.guid);
    if (!published) throw host.fail('error', 'The comic is not in the reviewed Duke Law catalogue.');
    // A CBZ is a ZIP of images. Stage the publisher's ZIP as-is under its comic extension.
    return { url: published.downloadUrl, fileName: published.fileName, format: published.format, sizeBytes: null };
  },
};

function verifyBase(config, host) {
  if (config.baseUrl.replace(/\/$/, '') !== BASE) {
    throw host.fail('error', 'Use the public Duke Law CSPD origin for this source.');
  }
}

function tokens(title) {
  return title.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
}
