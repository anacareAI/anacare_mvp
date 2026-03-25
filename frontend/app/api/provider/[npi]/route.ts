import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000'
const TOKEN = 'sandbox-token-demo'

export async function GET(
  _req: NextRequest,
  { params }: { params: { npi: string } }
) {
  try {
    const res = await fetch(`${API_URL}/v1/providers/${params.npi}`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch {
    return NextResponse.json({ detail: 'Provider lookup unavailable.' }, { status: 503 })
  }
}
