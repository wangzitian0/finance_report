export function shouldProxyApiToLocalBackend() {
    return process.env.NODE_ENV !== 'production' && (process.env.NEXT_PUBLIC_API_URL ?? '') === '';
}

/** @type {import('next').NextConfig} */
const nextConfig = {
    output: 'standalone',
    async redirects() {
        return [
            {
                source: '/',
                destination: '/dashboard',
                permanent: false,
            },
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
