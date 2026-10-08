// Pushes a "new_media" event to every receiver through Ably (real-time, no polling).
import { checkPassword } from './_auth.js';

const CHANNEL = process.env.ABLY_CHANNEL || 'media';

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

  const key = process.env.ABLY_PUBLISH_KEY;
  if (!key) return res.status(500).json({ error: 'ABLY_PUBLISH_KEY not configured' });

  const r = await fetch(`https://rest.ably.io/channels/${encodeURIComponent(CHANNEL)}/messages`, {
    method: 'POST',
    headers: {
      Authorization: 'Basic ' + Buffer.from(key).toString('base64'),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      name: 'new_media',
      data: JSON.stringify({ url, type, filename: String(filename || '').slice(0, 200) }),
    }),
  });

  if (!r.ok) {
    const detail = await r.text();
    return res.status(502).json({ error: 'Broadcast failed', detail });
  }
  return res.status(200).json({ status: 'sent', url, type, filename });
}
