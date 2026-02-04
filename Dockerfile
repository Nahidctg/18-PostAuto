FROM python:3.10-slim-buster

WORKDIR /app

# FFmpeg ইন্সটল করা হচ্ছে (ভিডিও থেকে ছবি বের করার জন্য বাধ্যতামূলক)
RUN apt-get update && apt-get install -y ffmpeg git

COPY requirements.txt requirements.txt
RUN pip3 install -U -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
