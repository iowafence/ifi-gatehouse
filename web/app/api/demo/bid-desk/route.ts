import { NextRequest } from 'next/server';
import { bidDesk } from '@/lib/demo';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) { return bidDesk(req); }
export async function POST(req: NextRequest) { return bidDesk(req); }
