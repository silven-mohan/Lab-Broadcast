// Daily cron: deletes media older than 24 hours so storage never piles up.
import { list, del } from '@vercel/blob';

export default async function handler(req, res) {
  const secret = process.env.CRON_SECRET;
  if (!secret || req.headers.authorization !== `Bearer ${secret}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const old = [];
  let cursor;
  do {
    const page = await list({ cursor, limit: 1000 });
    for (const b of page.blobs) {
      if (new Date(b.uploadedAt).getTime() < cutoff) old.push(b.url);
    }
    cursor = page.hasMore ? page.cursor : undefined;
  } while (cursor);

  if (old.length) await del(old);
  return res.status(200).json({ deleted: old.length });
}
