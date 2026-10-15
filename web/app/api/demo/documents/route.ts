import { NextRequest, NextResponse } from 'next/server';
import { listDocuments } from '@/lib/dp001';
import { allow, clientIp } from '@/lib/limits';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) {
  if (!allow(`doc:${clientIp(req.headers)}`, 300, 60_000)) return NextResponse.json({ error: 'Too many requests. Slow down.' }, { status: 429 });
  const r = await listDocuments();
  if (!r) return NextResponse.json({ error: 'Bid documents are not available in this build.' }, { status: 404, headers: { 'Cache-Control': 'no-store' } });
  return NextResponse.json(r, { headers: { 'Cache-Control': 'no-store' } });
}
