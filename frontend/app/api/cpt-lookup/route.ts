import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000'
// Sandbox token — the FastAPI stub accepts any bearer value
const TOKEN = 'sandbox-token-demo'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const res = await fetch(`${API_URL}/v1/cpt-lookup`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${TOKEN}`,
      },
      body: JSON.stringify(body),
    })
    const data = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    return NextResponse.json(
      { detail: 'CPT lookup unavailable. Check that the API is running.' },
      { status: 503 }
    )
  }
}
