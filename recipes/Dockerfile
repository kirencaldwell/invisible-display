FROM alpine:3.20
RUN apk add --no-cache python3
WORKDIR /app
COPY server.py index.html /app/
CMD ["python3", "-u", "/app/server.py"]
