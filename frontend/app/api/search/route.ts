import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000'
const TOKEN = 'sandbox-token-demo'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const res = await fetch(`${API_URL}/v1/rank-providers`, {
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
      { detail: 'Provider search unavailable. Check that the API is running.' },
      { status: 503 }
    )
  }
}
