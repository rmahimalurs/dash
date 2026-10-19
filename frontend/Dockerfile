# ─── Stage 1: Build ───────────────────────────────────────────────────────────
# Node 22 LTS — required by Vite 8 (Node ^20.19 || >=22.12)
FROM node:22-alpine AS builder

WORKDIR /app

# Copy package files first for layer caching
COPY package.json package-lock.json* ./

# Install all dependencies (including dev) for build
RUN npm ci

# Copy source
COPY . .

# Build the production bundle
RUN npm run build

# ─── Stage 1b: Vite dev server ────────────────────────────────────────────────
# docker-compose targets this stage. Vite binds to localhost by default, which a
# published port cannot reach from outside the container, hence --host.
FROM node:22-alpine AS dev

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]

# ─── Stage 2: Serve with nginx ────────────────────────────────────────────────
FROM nginx:alpine AS runner

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Use non-root user for security
RUN chown -R nginx:nginx /usr/share/nginx/html && \
    chmod -R 755 /usr/share/nginx/html

EXPOSE 80

# Validate nginx config on startup
CMD ["nginx", "-g", "daemon off;"]
