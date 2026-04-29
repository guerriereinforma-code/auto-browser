import { mkdir, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
// Patchright is a drop-in undetected fork of Playwright that launches
// Chromium without the automation signals (Runtime.enable / Console.enable /
// --enable-automation) that Cloudflare-class detectors flag. Same API as
// playwright, so the launchServer call below stays identical.
import { chromium } from "patchright";

const width = Number.parseInt(process.env.BROWSER_WIDTH || "1280", 10);
const height = Number.parseInt(process.env.BROWSER_HEIGHT || "800", 10);
const endpointFile = process.env.BROWSER_WS_ENDPOINT_FILE || "/data/profile/browser-ws-endpoint.txt";
const host = process.env.PLAYWRIGHT_SERVER_HOST || "0.0.0.0";
const port = Number.parseInt(process.env.PLAYWRIGHT_SERVER_PORT || "9223", 10);
const advertisedHost = process.env.PLAYWRIGHT_SERVER_ADVERTISED_HOST || "browser-node";
const launchLang = process.env.BROWSER_LANG || "it-IT,it";
const extraArgs = (process.env.BROWSER_EXTRA_ARGS || "")
  .split(/\s+/)
  .map((s) => s.trim())
  .filter(Boolean);

const browserServer = await chromium.launchServer({
  headless: false,
  chromiumSandbox: false,
  host,
  port,
  downloadsPath: "/data/downloads",
  args: [
    `--window-size=${width},${height}`,
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--disable-background-networking",
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    `--lang=${launchLang}`,
    "--disable-notifications",
    ...extraArgs,
  ],
});

const rawEndpoint = new URL(browserServer.wsEndpoint());
rawEndpoint.hostname = advertisedHost;
rawEndpoint.port = String(port);
const advertisedEndpoint = rawEndpoint.toString();

await mkdir(dirname(endpointFile), { recursive: true });
const tmpFile = `${endpointFile}.tmp`;
await writeFile(tmpFile, advertisedEndpoint, "utf-8");
await rename(tmpFile, endpointFile);
console.log(`wrote ${endpointFile}: ${advertisedEndpoint}`);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, async () => {
    await browserServer.close();
    process.exit(0);
  });
}

await new Promise((resolve) => browserServer.on("close", resolve));
