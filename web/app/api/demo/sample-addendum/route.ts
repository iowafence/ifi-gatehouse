import { sampleAddendum } from '@/lib/dp001';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET() {
  const bytes = await sampleAddendum();
  if (!bytes) return new Response(JSON.stringify({ error: 'The sample is not available.' }), { status: 404, headers: { 'content-type': 'application/json' } });
  return new Response(new Uint8Array(bytes), { status: 200, headers: { 'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="ADDENDUM_02.pdf"', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' } });
}
