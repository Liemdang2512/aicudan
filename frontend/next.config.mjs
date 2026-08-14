/** @type {import('next').NextConfig} */
const nextConfig = {
  // Standalone output: Docker image chỉ copy những file cần thiết (~300MB → ~50MB)
  output: "standalone",

  // Tắt X-Powered-By header để giảm payload nhỏ và ẩn thông tin stack
  poweredByHeader: false,

  // Bật gzip/brotli compression cho tất cả responses
  compress: true,

  // HTTP Cache-Control headers cho static assets trong public/
  async headers() {
    return [
      {
        // Ảnh tĩnh trong public/ (logo, icons, placeholders)
        source: "/:path*\\.(jpg|jpeg|png|gif|webp|svg|ico)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=86400, stale-while-revalidate=604800",
          },
        ],
      },
      {
        // Font files
        source: "/:path*\\.(woff|woff2|ttf|otf|eot)",
        headers: [
          {
            key: "Cache-Control",
            value: "public, max-age=31536000, immutable",
          },
        ],
      },
    ]
  },

  // Webpack: tách chunk cho các thư viện lớn ít thay đổi → browser cache tốt hơn
  webpack(config) {
    config.optimization.splitChunks = {
      ...config.optimization.splitChunks,
      cacheGroups: {
        ...config.optimization.splitChunks?.cacheGroups,
        // xlsx (~450KB) → chunk riêng, chỉ tải khi cần
        xlsx: {
          test: /[\\/]node_modules[\\/]xlsx[\\/]/,
          name: "vendor-xlsx",
          chunks: "all",
          priority: 30,
        },
        // lucide-react → chunk riêng vì được dùng ở nhiều trang
        lucide: {
          test: /[\\/]node_modules[\\/]lucide-react[\\/]/,
          name: "vendor-lucide",
          chunks: "all",
          priority: 20,
        },
        // Radix UI → chunk riêng
        radix: {
          test: /[\\/]node_modules[\\/]@radix-ui[\\/]/,
          name: "vendor-radix",
          chunks: "all",
          priority: 10,
        },
      },
    };
    return config;
  },
};

export default nextConfig;
