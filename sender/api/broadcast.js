// Announces a new media file to every receiver.
// Stores the newest event in Redis; receivers poll /api/latest and pick it up within a few seconds.
import { randomUUID } from 'node:crypto';
import { checkPassword } from './_auth.js';
import { redis, LATEST_KEY } from './_store.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });

  const { password, url, filename, type } = req.body || {};
  if (!checkPassword(password)) return res.status(401).json({ error: 'Unauthorized' });

  // Only accept URLs that point at our own Vercel Blob store.
  let host;
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:') throw new Error();
    host = u.hostname;
  } catch {
    return res.status(400).json({ error: 'Invalid URL' });
  }
  if (!host.endsWith('.public.blob.vercel-storage.com')) {
    return res.status(400).json({ error: 'URL must be a Vercel Blob URL' });
  }
  if (!['image', 'video'].includes(type)) {
    return res.status(400).json({ error: 'Invalid media type' });
  }

  const event = {
    id: `${Date.now()}-${randomUUID().slice(0, 8)}`, // new id every send, so re-sending the same file replays it
    url,
    type,
    filename: String(filename || '').slice(0, 200),
    ts: Date.now(),
  };

  try {
    // Expire after 24h, matching the blob cleanup cron, so a stale event never points at a deleted file.
    await redis(['SET', LATEST_KEY, JSON.stringify(event), 'EX', 86400]);
  } catch (err) {
    return res.status(502).json({ error: 'Broadcast failed', detail: err.message });
  }
  return res.status(200).json({ status: 'sent', url, type, filename: event.filename });
}
