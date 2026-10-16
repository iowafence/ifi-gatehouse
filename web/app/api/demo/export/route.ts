import { NextRequest } from 'next/server';
import { bidExport } from '@/lib/demo';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) { return bidExport(req); }
