import type { NextConfig } from "next";

// CLIPBOT_STATIC=1 builds the dashboard as plain files in out/ for the desktop app, where
// ClipBot's own API serves them (and sets the security headers). The /api proxy route is named
// route.proxy.ts so that only the Node server build below, which lists "proxy.ts", includes it.
const desktopApp = process.env.CLIPBOT_STATIC === "1";

const config: NextConfig = desktopApp
  ? {
      output: "export",
      poweredByHeader: false,
    }
  : {
      output: "standalone",
      outputFileTracingRoot: process.cwd(),
      pageExtensions: ["tsx", "ts", "jsx", "js", "proxy.ts"],
      poweredByHeader: false,
      async headers() {
        return [
          {
            source: "/(.*)",
            headers: [
              { key: "X-Frame-Options", value: "DENY" },
              { key: "X-Content-Type-Options", value: "nosniff" },
              { key: "Referrer-Policy", value: "same-origin" },
            ],
          },
        ];
      },
    };
export default config;
