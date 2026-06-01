# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port 8000 (documentation only - not accessible from host)
EXPOSE 8000

# Run uvicorn bound to 0.0.0.0 to allow Docker network access
CMD ["uvicorn", "doc_search.startup.api:app", "--host", "0.0.0.0", "--port", "8000"]
