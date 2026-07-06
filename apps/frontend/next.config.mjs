export function shouldProxyApiToLocalBackend() {
    return process.env.NODE_ENV !== 'production' && (process.env.NEXT_PUBLIC_API_URL ?? '') === '';
}

const securityHeaders = [
    {
        key: 'Content-Security-Policy',
        value: [
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            // #963 / AC16.33.5: the Stage 1 review embeds the statement document
            // as a same-origin `blob:` object URL (fetched with auth), so the
            // iframe needs an explicit frame-src. Without it the iframe falls
            // back to `default-src 'self'`, which excludes `blob:` and renders
            // the browser "This content is blocked" message.
            "frame-src 'self' blob:",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            "style-src 'self' 'unsafe-inline'",
            // The OpenPanel analytics SDK (EPIC-024) loads its script from the
            // self-hosted host (Analytics.tsx DEFAULT_OPENPANEL_API_URL). Without
            // it here the browser blocks op1.js and telemetry silently dies
            // (#1623). connect-src already covers *.zitian.party for the beacon POSTs.
            "script-src 'self' 'unsafe-inline' https://openpanel.zitian.party",
            "connect-src 'self' https://*.zitian.party",
            "form-action 'self'",
        ].join('; '),
    },
    {
        key: 'Strict-Transport-Security',
        value: 'max-age=31536000; includeSubDomains; preload',
    },
    {
        key: 'X-Frame-Options',
        value: 'DENY',
    },
    {
        key: 'X-Content-Type-Options',
        value: 'nosniff',
    },
    {
        key: 'Referrer-Policy',
        value: 'strict-origin-when-cross-origin',
    },
    {
        key: 'Permissions-Policy',
        value: 'camera=(), microphone=(), geolocation=(), payment=()',
    },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'standalone',
    async headers() {
        return [
            {
                source: '/:path*',
                headers: securityHeaders,
            },
        ];
    },
    // EPIC-022: align legacy routes onto the everyday-user IA. `/` now renders
    // the smart Home inside the app shell, so it is no longer redirected.
    async redirects() {
        return [
            { source: '/dashboard', destination: '/', permanent: true },
            { source: '/events', destination: '/notifications', permanent: true },
            { source: '/assets', destination: '/portfolio', permanent: true },
            { source: '/statements/upload', destination: '/upload', permanent: true },
            { source: '/statements', destination: '/upload', permanent: true },
            // EPIC-022 PR2: the standalone Review Queue folds into the notification center.
            { source: '/review', destination: '/notifications', permanent: true },
            // EPIC-022 AC22.21.4: the three settings pages merge into one tabbed
            // /settings surface; the old paths resolve to the matching tab.
            { source: '/settings/general', destination: '/settings?tab=general', permanent: true },
            { source: '/settings/ai', destination: '/settings?tab=ai', permanent: true },
            { source: '/settings/llm', destination: '/settings?tab=llm', permanent: true },
        ];
    },
    // Local development without an explicit API URL proxies /api/* to the backend.
    // Containerized and production deployments keep same-origin /api/* routes intact.
    async rewrites() {
        if (!shouldProxyApiToLocalBackend()) return [];
        return [{ source: '/api/:path*', destination: 'http://localhost:8000/:path*' }];
    },
};

export default nextConfig;
