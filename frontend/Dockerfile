FROM node:20-slim

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# Conteneur non-root (Phase 8 — sécurité). Note dev : avec le bind-mount
# ./frontend:/app de docker-compose, l'UID du conteneur (1000, "node")
# peut ne pas correspondre à l'utilisateur hôte — si ça bloque l'écriture
# en local, ajuster l'UID/GID au build ou retirer USER en dev.
USER node

EXPOSE 5173

CMD ["npm", "run", "dev"]
