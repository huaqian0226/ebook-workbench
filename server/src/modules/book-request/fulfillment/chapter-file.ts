import { constants } from 'node:fs';
import { open } from 'node:fs/promises';
import { join } from 'node:path';
import { Readable } from 'node:stream';

/** This fixed URI designates an immutable EPUB on a read-only volume. No network request is made. */
export function chapterFileName(uri: string): string | null {
  const m = /^http:\/\/chapter-books:8080\/books\/([a-z0-9-]{1,80})\/([a-z0-9-]{1,80})\.epub$/.exec(uri);
  return m && m[0] === uri ? `${m[1]}-${m[2]}.epub` : null;
}

export async function openChapterFile(root: string, name: string, offset: number): Promise<Response> {
  if (!/^[a-z0-9-]{3,161}\.epub$/.test(name)) throw new Error('Unknown chapter edition');
  const file = await open(join(root, name), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const stat = await file.stat();
    if (!stat.isFile() || !stat.size || stat.size > 256 * 1024 * 1024) throw new Error('Chapter edition unavailable');
    const headers = new Headers({ 'content-type': 'application/epub+zip', etag: `"${name}-${stat.size}"` });
    if (offset >= stat.size) {
      await file.close();
      headers.set('content-range', `bytes */${stat.size}`);
      return new Response(null, { status: 416, headers });
    }
    headers.set('content-length', String(stat.size - offset));
    if (offset > 0) headers.set('content-range', `bytes ${offset}-${stat.size - 1}/${stat.size}`);
    const stream = Readable.toWeb(file.createReadStream({ start: offset }));
    return new Response(stream as ReadableStream<Uint8Array<ArrayBuffer>>, { status: offset ? 206 : 200, headers });
  } catch (error) {
    await file.close();
    throw error;
  }
}
