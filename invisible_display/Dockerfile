FROM alpine:3.20
RUN apk add --no-cache python3 py3-pillow py3-numpy tzdata font-dejavu
WORKDIR /app
COPY ha.py commute.py render.py demo.py server.py /app/
CMD ["python3", "-u", "/app/server.py"]
