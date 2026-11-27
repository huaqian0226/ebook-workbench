import assert from "node:assert/strict";
import test from "node:test";
import plugin from "./index.mjs";

const root = "https://gutenberg.pglaf.org/cache/epub/23962/";
const config = { baseUrl: "http://gutenberg:8080" };
const query = { title: "西遊記", authors: [], mediaKind: "ebook", limit: 8 };
const hit = { title: "西遊記", providerId: "23962", languageCode: "zh", authors: ["Wu, Cheng'en"] };
function host(listing) {
  return {
    fail: (_code, msg) => Error(msg),
    fetch: async (url) => {
      if (url.startsWith(config.baseUrl + "/search?")) return Response.json({ matches: [hit] });
      assert.equal(url, root);
      return new Response(listing);
    },
  };
}
test("offer the actual published EPUB and ignore unrelated links", async () => {
  const h = host('<a href="pg23962-images-3.epub">EPUB</a><a href="pg9.epub">extra</a>');
  const rows = await plugin.search(query, config, h);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].downloadUrl, root + "pg23962-images-3.epub");
  assert.equal((await plugin.resolveFile(rows[0], config, h)).url, rows[0].downloadUrl);
});
test("a catalogue record alone supplies no release", async () => {
  assert.deepEqual(await plugin.search(query, config, host('<a href="pg23962.txt">TXT</a>')), []);
});
test("a changed release URL cannot redirect a grab", async () => {
  const h = host('<a href="pg23962.epub">EPUB</a>');
  const [row] = await plugin.search(query, config, h);
  await assert.rejects(() => plugin.resolveFile({ ...row, downloadUrl: "https://example.com/file.epub" }, config, h));
});
test("a simplified title can match the mirror catalogue through its traditional spelling", async () => {
  const inner = host('<a href="pg23962.epub">EPUB</a>');
  const mocks = {
    ...inner,
    fetch: async (url) => {
      if (url.startsWith("https://zh.wikipedia.org/")) return Response.json({ parse: { text: "<p>西遊記\n</p>" } });
      if (url.startsWith(config.baseUrl) && new URL(url).searchParams.get("query") === "西游记") return Response.json({ matches: [] });
      return inner.fetch(url);
    },
  };
  const result = await plugin.search({ ...query, title: "西游记" }, config, mocks);
  assert.equal(result[0].guid, "23962");
});
