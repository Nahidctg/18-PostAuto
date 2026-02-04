FROM python:3.10-slim-buster

# ওয়ার্কিং ডিরেক্টরি সেট করা
WORKDIR /app

# FFmpeg এবং প্রয়োজনীয় টুলস ইন্সটল করা
RUN apt-get update && apt-get install -y ffmpeg git

# পাইথন প্যাকেজ ইন্সটল করা
COPY requirements.txt requirements.txt
RUN pip3 install -U -r requirements.txt

# সব ফাইল কপি করা
COPY . .

# বট রান করা (আপনার মেইন ফাইলের নাম যদি main.py হয়)
CMD ["python3", "main.py"]
