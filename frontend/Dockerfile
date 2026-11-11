# LedgerLine — Production Frontend Dockerfile
# Stage 1: Build the static application bundle with Node.js 22 LTS
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies using exact lockfile
COPY package.json package-lock.json ./
RUN npm ci

# Copy frontend source files
COPY . .

# Build argument for API base URL (empty defaults to same-origin reverse proxy)
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

# Compile TypeScript and bundle Vite production assets
RUN npm run build

# Stage 2: Serve static production assets with official stable lightweight Nginx
FROM nginx:stable-alpine AS runner

# Copy bundled production assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy URL sanitization script into docker-entrypoint hooks
COPY 18-sanitize-backend-url.envsh /docker-entrypoint.d/18-sanitize-backend-url.envsh
RUN chmod +x /docker-entrypoint.d/18-sanitize-backend-url.envsh

# Create templates directory and copy Nginx configuration template for dynamic runtime envsubst
RUN mkdir -p /etc/nginx/templates && rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/templates/default.conf.template

# Default runtime environment variables:
# - PORT: 80 for local Docker Compose (Render dynamically overrides to 10000)
# - BACKEND_PUBLIC_URL: internal Compose address (Render dynamically overrides to https://<backend>.onrender.com)
ENV PORT=80 \
    BACKEND_PUBLIC_URL=http://backend:10000

EXPOSE 80 10000

# Health check probe for web server readiness
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD sh -c "wget --no-verbose --tries=1 --spider http://127.0.0.1:${PORT:-80}/ || exit 1"

CMD ["nginx", "-g", "daemon off;"]
