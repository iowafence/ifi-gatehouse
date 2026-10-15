import { NextRequest, NextResponse } from 'next/server';
import { scopeDraft } from '@/lib/dp001';
import { allow, clientIp } from '@/lib/limits';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) {
  if (!allow(`draft:${clientIp(req.headers)}`, 300, 60_000)) return NextResponse.json({ error: 'Too many requests. Slow down.' }, { status: 429 });
  const d = await scopeDraft();
  if (!d) return NextResponse.json({ error: 'No scope draft is available in this build.' }, { status: 404, headers: { 'Cache-Control': 'no-store' } });
  return NextResponse.json(d, { headers: { 'Cache-Control': 'no-store' } });
}
