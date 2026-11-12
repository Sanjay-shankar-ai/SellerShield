# ==============================================================================
# Multi-Stage Dockerfile for SellerShield AI (Production on Google Cloud Run)
# ==============================================================================

# STAGE 1: Build React Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# STAGE 2: Python FastAPI Production Server
FROM python:3.12-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend code, static assets, and prompts
COPY backend ./backend
COPY static ./static

# Copy compiled frontend from Stage 1
COPY --from=frontend-builder /app/dist ./dist

# Set environment defaults for Google Cloud Run
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Run uvicorn on port 8080 (Cloud Run standard)
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080"]
