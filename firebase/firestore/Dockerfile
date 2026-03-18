FROM ubuntu:24.04

RUN apt update && \
    apt install -y curl openjdk-25-jdk && \
    curl -fsSL https://deb.nodesource.com/setup_24.x | bash - && \
    apt install -y nodejs && \
    npm install -g firebase-tools
