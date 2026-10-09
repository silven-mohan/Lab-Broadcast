// Tiny Upstash Redis client over plain HTTPS (no SDK needed).
// The Vercel Marketplace integration sets KV_REST_API_URL / KV_REST_API_TOKEN;
// a database created directly on upstash.com uses UPSTASH_REDIS_REST_URL / _TOKEN. Both work here.
const URL_ = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
const TOKEN = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;

export const LATEST_KEY = 'latest_media';

export async function redis(command) {
  if (!URL_ || !TOKEN) throw new Error('Redis is not configured (KV_REST_API_URL / KV_REST_API_TOKEN missing)');
  const r = await fetch(URL_, {
    method: 'POST',
    headers: { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(command),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok || j.error) throw new Error(j.error || `Redis HTTP ${r.status}`);
  return j.result;
}
