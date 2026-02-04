FROM python:3.9-slim-buster

# FFmpeg এবং অন্যান্য প্রয়োজনীয় টুলস ইনস্টল করা
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# কাজের ফোল্ডার সেট করা
WORKDIR /app

# রিকোয়ারমেন্টস ইনস্টল করা
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# সব ফাইল কপি করা
COPY . .

# বট রান করা
CMD ["python3", "main.py"]
