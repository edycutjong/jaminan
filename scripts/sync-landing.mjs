// One Vercel project: the static landing + deck (docs/) and the evidence files are served from public/ at the site root;
// the app lives under /app. Copies run before dev and build, so docs/ stays the only source.
import { cpSync, mkdirSync, readdirSync } from "node:fs";

for (const name of readdirSync("docs")) cpSync(`docs/${name}`, `public/${name}`, { recursive: true });
mkdirSync("public/evidence", { recursive: true });
for (const name of readdirSync("evidence")) cpSync(`evidence/${name}`, `public/evidence/${name}`, { recursive: true });
