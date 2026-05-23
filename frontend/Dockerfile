FROM node:22-slim

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend ./

EXPOSE 5173

CMD ["npm", "run", "dev:docker"]
