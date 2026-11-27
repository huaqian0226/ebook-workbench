import assert from 'node:assert/strict';
import test from 'node:test';
import plugin from '../sources/chapter-books/index.mjs';

const config = { baseUrl: 'http://chapter-books:8080' };
const book = {
  slug: 'test-book', title: '示例書', author: '示例作者', language: 'zh-Hant',
  editionId: 'r21', sourceUrl: 'https://zh.wikisource.org/w/index.php?oldid=21',
  sizeBytes: 1234, chapterCount: 2,
};

const host = {
  fail(code, reason) {
    return new Error(`${code}: ${reason}`);
  },
  async fetch(url, options = {}) {
    assert.match(String(url), /^http:\/\/chapter-books:8080\//);
    const path = new URL(url).pathname;
    if (path === '/healthz') return Response.json({ status: 'ready', books: 1 });
    if (path === '/search') {
      assert.equal(new URL(url).searchParams.get('q'), '示例书');
      return Response.json({ books: [book] });
    }
    assert.equal(path, '/books/test-book/r21.epub');
    assert.equal(options.method, 'HEAD');
    return new Response(null, { headers: { 'Content-Type': 'application/epub+zip', 'Content-Length': '1234' } });
  },
};

test('BookOrbit search and resolve use the exact approved version and a single EPUB file', async () => {
  assert.equal((await plugin.test(config, host)).success, true);
  const [release] = await plugin.search({ title: '示例书', mediaKind: 'ebook', limit: 5 }, config, host);
  assert.equal(release.bookTitle, '示例書');
  assert.equal(release.infoUrl, book.sourceUrl);
  assert.equal(release.downloadUrl, config.baseUrl + '/books/test-book/r21.epub');
  assert.equal(release.primaryFileCount, 1);
  assert.deepEqual(await plugin.resolveFile(release, config, host), {
    url: release.downloadUrl, fileName: '示例書.epub', sizeBytes: 1234, format: 'epub',
  });
  assert.deepEqual(await plugin.search({ title: '示例书', mediaKind: 'audiobook', limit: 5 }, config, host), []);
  for (const rejected of [{ ...release, guid: 'test-book/../r21' }, { ...release, downloadUrl: 'https://elsewhere.invalid/book.epub' }]) {
    await assert.rejects(plugin.resolveFile(rejected, config, host), /error:/);
  }
});

test('an unavailable or non-EPUB artifact is refused before accepting it', async () => {
  const [release] = await plugin.search({ title: '示例书', mediaKind: 'ebook', limit: 5 }, config, host);
  await assert.rejects(plugin.resolveFile(release, config, {
    ...host,
    async fetch() { return new Response(null, { status: 404 }); },
  }), /error:/);
  await assert.rejects(plugin.resolveFile(release, config, {
    ...host,
    async fetch() {
      return new Response(null, { headers: { 'Content-Type': 'text/html', 'Content-Length': '1234' } });
    },
  }), /error:/);
});
