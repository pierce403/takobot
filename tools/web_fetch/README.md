# web_fetch

Fetch a URL and return a readable text extract.

Standard shape:

- Tool name: `web_fetch`
- Purpose: deterministic web retrieval for evidence-backed answers

Input examples:

- `{"url":"https://example.com"}`
- `{"url":"https://example.com","render_js":true}`
- `{"url":"https://example.com","max_chars":4000,"timeout_s":25}`

Notes:

- `render_js=true` attempts Playwright first, then falls back to plain HTTP extraction.
- Supports only `http://` and `https://` URLs.
