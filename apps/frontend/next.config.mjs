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
    // Rewrite for local development only - proxies /api/* to backend on localhost:8000
    // In containerized/production, frontend and backend share same origin, no rewrite needed
    async rewrites() {
        return [
            {
                source: '/api/:path*',
                destination: 'http://localhost:8000/:path*',
            },
        ];
    },
};

export default nextConfig;
