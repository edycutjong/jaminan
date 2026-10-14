import type { NextConfig } from "next";

// In development the FastAPI app runs on :8000 (npm run dev:api); on Vercel /api/* is the Python function.
const config: NextConfig = {
  async rewrites() {
    return process.env.NODE_ENV === "development"
      ? [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }]
      : [];
  },
  poweredByHeader: false,
};
export default config;
