import { NextRequest } from 'next/server';
import { flightRecorder } from '@/lib/demo';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function GET(req: NextRequest) { return flightRecorder(req); }
