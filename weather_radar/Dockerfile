FROM alpine:3.20
RUN apk add --no-cache python3 py3-pillow tzdata font-dejavu
WORKDIR /app
COPY radar.py /app/
CMD ["python3", "-u", "/app/radar.py"]
