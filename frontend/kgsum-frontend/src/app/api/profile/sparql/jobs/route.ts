import {NextRequest, NextResponse} from "next/server";

export const runtime = "nodejs";

const API_BASE_URL = process.env.CLASSIFICATION_API_URL || "http://localhost:5000";

export async function POST(request: NextRequest) {
    const body = await request.json();
    const response = await fetch(`${API_BASE_URL}/api/v1/profile/sparql/jobs`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "Accept": "application/json",
            ...(request.headers.get("authorization")
                ? {"Authorization": request.headers.get("authorization") as string}
                : {}),
        },
        body: JSON.stringify(body),
    });

    const payload = await response.json().catch(() => ({}));
    return NextResponse.json(payload, {status: response.status});
}
