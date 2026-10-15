import { NextRequest } from 'next/server';
import { portfolio } from '@/lib/demo';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) { return portfolio(req); }
