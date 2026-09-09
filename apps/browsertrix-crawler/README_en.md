## Introduction

**Browsertrix Crawler** is Webrecorder's high-fidelity browser-based web crawler. It runs browser workers in a single Docker container and creates WARC/WACZ web archives. This template supports multiple seed sites and interval-based recurring crawls.

## Features

- **Recurring Multi-site Crawls**: Configure multiple seed URLs in seeds.txt and automatically begin another crawl after the configured interval.
- **Automatic Cross-run Deduplication**: A persistent Redis content index stores duplicate content as compact WARC revisit records across recurring crawls.
- **Replayable Archives**: WACZ output is enabled by default and crawl results are persisted locally.
- **Agent Change API**: Indexes newly observed content hashes and exposes change lists, payloads, and URL history through token-protected REST and MCP endpoints.

- **On-demand crawls**: Request a crawl with REST `POST /api/v1/crawls` or MCP `trigger_crawl`. Pending requests coalesce and run after any active crawl. See [API documentation](CHANGE_API.md).
