FROM alpine:3.24
RUN apk add --no-cache python3
WORKDIR /app
COPY server.py index.html /app/
CMD ["python3", "-u", "/app/server.py"]
