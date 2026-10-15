import { NextRequest } from 'next/server';
import { state } from '@/lib/demo';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) { return state(req); }
