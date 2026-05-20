import {NextRequest, NextResponse} from "next/server";

export const runtime = "nodejs";

const API_BASE_URL = process.env.CLASSIFICATION_API_URL || "http://localhost:5000";

export async function GET(
    request: NextRequest,
    context: { params: Promise<{ jobId: string }> }
) {
    const {jobId} = await context.params;
    const response = await fetch(`${API_BASE_URL}/api/v1/profile/jobs/${encodeURIComponent(jobId)}`, {
        method: "GET",
        headers: {
            "Accept": "application/json",
            ...(request.headers.get("authorization")
                ? {"Authorization": request.headers.get("authorization") as string}
                : {}),
        },
    });

    const payload = await response.json().catch(() => ({}));
    return NextResponse.json(payload, {status: response.status});
}
