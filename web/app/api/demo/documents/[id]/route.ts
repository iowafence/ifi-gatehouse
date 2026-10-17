import { NextRequest, NextResponse } from 'next/server';
import { documentBytes } from '@/lib/dp001';
import { allow, clientIp } from '@/lib/limits';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
// Serves a registered bid document only after its SHA-256 matches the registered identity. The id is a lookup key, never a path.
export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  if (!allow(`docget:${clientIp(req.headers)}`, 120, 60_000)) return NextResponse.json({ error: 'Too many requests. Slow down.' }, { status: 429 });
  const { id } = await ctx.params;
  const r = await documentBytes(id);
  if (!r) return NextResponse.json({ error: 'Unknown document' }, { status: 404 });
  if (!r.bytes) return NextResponse.json({ error: 'Document failed its identity check and is not served.' }, { status: 409 });
  return new NextResponse(new Uint8Array(r.bytes), { status: 200, headers: {
    'Content-Type': 'application/pdf', 'Content-Disposition': `${req.nextUrl.searchParams.get('download') === '1' ? 'attachment' : 'inline'}; filename="${String(r.doc.filename).replace(/[^A-Za-z0-9._-]/g, '_')}"`,
    'X-Document-Sha256': r.doc.sha256, 'Cache-Control': 'private, max-age=300' } });
}
