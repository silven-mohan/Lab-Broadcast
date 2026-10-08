// Issues short-lived tokens so the BROWSER uploads straight to Vercel Blob.
// The file never passes through this function, so the 4.5 MB body limit doesn't apply.
import { handleUpload } from '@vercel/blob/client';
import { checkPassword } from './_auth.js';

export default async function handler(req, res) {
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  try {
    const json = await handleUpload({
      body: req.body,
      request: req,
      onBeforeGenerateToken: async (_pathname, clientPayload) => {
        if (!checkPassword(clientPayload)) throw new Error('Unauthorized');
        return {
          allowedContentTypes: ['image/*', 'video/*'],
          addRandomSuffix: true, // unguessable URLs
        };
      },
      onUploadCompleted: async () => {}, // not needed; /api/broadcast does the announcing
    });
    return res.status(200).json(json);
  } catch (err) {
    return res.status(400).json({ error: err.message });
  }
}
