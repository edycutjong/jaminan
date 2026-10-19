import type { NextConfig } from "next";

// One Vercel project: the landing (docs/, copied into public/ by scripts/sync-landing.mjs) at /, the app under /app.
// In development the FastAPI app runs on :8000 (npm run dev:api); on Vercel /api/* is the Python function.
const appRoutes = ["shop", "r", "judge", "integrations"];

const config: NextConfig = {
  async redirects() {
    // Links printed before the move (QR codes, PayPal return URLs, the demo video) keep working.
    return appRoutes.flatMap((p) => [
      { source: `/${p}`, destination: `/app/${p}`, permanent: false },
      { source: `/${p}/:path*`, destination: `/app/${p}/:path*`, permanent: false },
    ]);
  },
  async rewrites() {
    return {
      beforeFiles: [
        { source: "/", destination: "/index.html" },
        { source: "/pitch", destination: "/pitch/index.html" },
      ],
      afterFiles: [],
      fallback:
        process.env.NODE_ENV === "development"
          ? [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }]
          : [],
    };
  },
  async headers() {
    return [
      { source: "/site/:path*", headers: [{ key: "Cache-Control", value: "public, max-age=604800" }] },
      { source: "/assets/:path*", headers: [{ key: "Cache-Control", value: "public, max-age=604800" }] },
      { source: "/evidence/:file*.md", headers: [{ key: "Content-Type", value: "text/plain; charset=utf-8" }] },
      { source: "/evidence/:file*.txt", headers: [{ key: "Content-Type", value: "text/plain; charset=utf-8" }] },
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
        ],
      },
    ];
  },
  poweredByHeader: false,
};
export default config;
