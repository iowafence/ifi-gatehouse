import { NextRequest } from 'next/server';
import { preview } from '@/lib/demo';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(req: NextRequest) { return preview(req); }
