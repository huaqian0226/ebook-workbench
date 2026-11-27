// Search the deployment's Gutenberg snapshot and verify files on the Foundation mirror.
const CATALOG = "http://gutenberg:8080";
const MIRROR = "https://gutenberg.pglaf.org/cache/epub/";
const LABEL = "Project Gutenberg · EPUB";
const variants = ["-images-3", "-images", ""];

async function get(url, host) {
  const response = await host.fetch(url, { headers: { "User-Agent": "BookOrbit/3.10 (ebook-workbench)" }, redirect: "manual" });
  if (response.status === 429) throw host.fail("throttled", "The catalogue requested a pause.");
  if (response.status !== 404 && !response.ok) throw host.fail("error", "Catalogue HTTP " + response.status);
  return response;
}

async function matches(title, author, limit, host) {
  const q = new URLSearchParams({ query: title, author, limit: String(limit) });
  const resp = await get(CATALOG + "/search?" + q, host);
  if (!resp.ok) throw host.fail("error", "Gutenberg catalogue unavailable.");
  return (await resp.json()).matches;
}

async function traditionalTitle(title, host) {
  // Ask the public MediaWiki variant converter only for a literal title after a catalogue miss.
  if (!/^[\p{Script=Han}\p{Nd} ·]{1,100}$/u.test(title)) return title;
  const params = new URLSearchParams({
    action: "parse",
    text: title,
    prop: "text",
    variant: "zh-hant",
    contentmodel: "wikitext",
    format: "json",
    formatversion: "2",
    disablelimitreport: "1",
    maxlag: "5",
  });
  const response = await get("https://zh.wikipedia.org/w/api.php?" + params, host);
  if (!response.ok) return title;
  return (await response.json()).parse?.text?.match(/<p>([\p{Script=Han}\p{Nd} ·]+)\s*<\/p>/u)?.[1] ?? title;
}

function verifyConfig(config, host) {
  if (config.baseUrl.replace(/\/$/, "") !== CATALOG) throw host.fail("error", "Use the internal Gutenberg catalogue URL.");
}

async function available(row, host) {
  const id = row.providerId;
  if (!/^[1-9][0-9]{0,8}$/.test(id)) return null;
  const directory = MIRROR + id + "/";
  const response = await get(directory, host);
  if (!response.ok) return null;
  const html = await response.text();
  const files = new Set(Array.from(html.matchAll(/\bhref\s*=\s*["']([^"']+)["']/gi), (m) => m[1]));
  const name = variants.map((v) => "pg" + id + v + ".epub").find((file) => files.has(file));
  if (!name) return null;
  return {
    guid: id,
    title: row.title,
    bookTitle: row.title,
    author: row.authors?.join(", ") || null,
    language: row.languageCode || null,
    format: "epub",
    infoUrl: directory,
    downloadUrl: directory + name,
    sizeBytes: null,
    seeders: null,
    leechers: null,
    freeleech: true,
    primaryFileCount: 1,
  };
}

export default {
  apiVersion: 1,
  version: "1.0.0",
  type: "gutenberg-files",
  label: LABEL,
  defaultBaseUrl: CATALOG,
  baseUrlHint: "Internal Gutenberg metadata service on the BookOrbit network.",
  requiresCredential: false,
  credentialKind: null,
  mediaKinds: ["ebook"],
  usesCategories: false,
  seedsBack: false,
  async search(query, config, host) {
    verifyConfig(config, host);
    const title = query.title.trim().slice(0, 200);
    if (!title || query.mediaKind !== "ebook" || query.limit <= 0) return [];
    const limit = Math.min(query.limit, 6);
    const author = (query.authors || []).join(" ").slice(0, 200);
    let rows = await matches(title, author, limit, host);
    if (!rows.length && /\p{Script=Han}/u.test(title)) {
      const variant = await traditionalTitle(title, host);
      if (variant !== title) rows = await matches(variant, author, limit, host);
    }
    const releases = [];
    for (let n = 0; n < Math.min(rows.length, limit); n += 2) {
      releases.push(...(await Promise.all(rows.slice(n, Math.min(n + 2, limit)).map((row) => available(row, host)))));
    }
    return releases.filter(Boolean);
  },
  async test(config, host) {
    verifyConfig(config, host);
    const rows = await matches("西遊記", "", 1, host);
    const result = rows.length && (await available(rows[0], host));
    return result ? { success: true, indexerName: LABEL } : { success: false, error: "The sample EPUB is unavailable." };
  },
  async resolveFile(release, config, host) {
    verifyConfig(config, host);
    const id = release.guid;
    if (!/^[1-9][0-9]{0,8}$/.test(id)) throw host.fail("error", "Invalid Gutenberg edition.");
    const name = variants.map((v) => "pg" + id + v + ".epub").find((f) => release.downloadUrl === MIRROR + id + "/" + f);
    if (!name) throw host.fail("error", "Unrecognised Gutenberg file.");
    return { url: release.downloadUrl, fileName: name, format: "epub", sizeBytes: null };
  },
};
