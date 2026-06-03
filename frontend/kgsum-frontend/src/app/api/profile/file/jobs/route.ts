import {NextRequest, NextResponse} from "next/server";

export const runtime = "nodejs";

const API_BASE_URL = process.env.CLASSIFICATION_API_URL || "http://localhost:5000";

export async function POST(request: NextRequest) {
    const formData = await request.formData();
    const store = request.nextUrl.searchParams.get("store") || "false";
    const response = await fetch(`${API_BASE_URL}/api/v1/profile/file/jobs?store=${encodeURIComponent(store)}`, {
        method: "POST",
        headers: {
            "Accept": "application/json",
            ...(request.headers.get("authorization")
                ? {"Authorization": request.headers.get("authorization") as string}
                : {}),
        },
        body: formData,
    });

    const payload = await response.json().catch(() => ({}));
    return NextResponse.json(payload, {status: response.status});
}
