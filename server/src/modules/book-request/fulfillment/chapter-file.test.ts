import { mkdtemp, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, it } from 'vitest';
import { chapterFileName, openChapterFile } from './chapter-file';

it('reads only a versioned flat publication from the mounted cache and resumes it', async () => {
  const root = await mkdtemp(join(tmpdir(), 'chapter-file-'));
  try {
    const name = chapterFileName('http://chapter-books:8080/books/work/v1.epub');
    expect(name).toBe('work-v1.epub');
    expect(chapterFileName('http://chapter-books:8080/books/other/path/v1.epub')).toBeNull();
    expect(chapterFileName('https://example.org/work.epub')).toBeNull();
    await writeFile(join(root, name!), 'archive');
    const r = await openChapterFile(root, name!, 2);
    expect(r.status).toBe(206);
    expect(r.headers.get('content-range')).toBe('bytes 2-6/7');
    expect(await r.text()).toBe('chive');
    await symlink(join(root, name!), join(root, 'link-v1.epub'));
    await expect(openChapterFile(root, 'link-v1.epub', 0)).rejects.toThrow();
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
