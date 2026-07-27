const port = process.env.DOCS_HUB_PORT ?? "8080";
const healthPath = process.argv[2] ?? "/healthz";
const response = await fetch(`http://127.0.0.1:${port}${healthPath}`, {
  signal: AbortSignal.timeout(4_000)
});
if (!response.ok) process.exit(1);
