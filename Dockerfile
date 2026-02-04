FROM python:3.10-slim-buster

WORKDIR /app

# FFmpeg এবং প্রয়োজনীয় সিস্টেম টুলস ইন্সটল
RUN apt-get update && apt-get install -y ffmpeg git

# পাইথন লাইব্রেরি ইন্সটল
COPY requirements.txt requirements.txt
RUN pip3 install -U -r requirements.txt

# কোড কপি এবং রান
COPY . .
CMD ["python3", "main.py"]
