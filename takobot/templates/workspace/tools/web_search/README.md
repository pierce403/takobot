# web_search

Run a web search and return structured results.

Standard shape:

- Tool name: `web_search`
- Purpose: live web discovery for current facts and external signal checks

Input examples:

- `{"query":"xmtp protocol update"}`
- `{"query":"hacker news top stories","max_results":5}`
- `{"query":"playwright python","include_page_text":true,"page_fetch_limit":2}`

Notes:

- Uses DuckDuckGo web endpoints for search result discovery.
- `include_page_text=true` performs follow-up page fetches for top results.
- For a specific URL body extraction, use `web_fetch`.
