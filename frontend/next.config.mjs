/** @type {import('next').NextConfig} */
const nextConfig = {
  // Bật standalone output để Docker image frontend nhỏ gọn:
  // Next.js sẽ copy chỉ những file cần thiết vào .next/standalone/
  // → runtime stage không cần toàn bộ node_modules (~300MB → ~50MB)
  output: "standalone",
};

export default nextConfig;
