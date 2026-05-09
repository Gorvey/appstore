## Introduction

**CPA Account Biopsy System** is a standalone sidecar service for CLIProxyAPI. It does not replace the main service and runs as a separate Docker service communicating via the management API.

## Features

- **Account Health Dashboard**: Pool health overview and per-account state display (unprobed, active, quota-limited, blocked, disabled)
- **Quota Window Visualization**: Displays weekly quota, code review weekly quota, and 5-hour quota windows
- **Request Statistics**: Shows request count, success, failures, and token usage
- **Account Management**: Manual enable, disable, and delete actions for accounts
- **Independent Dashboard**: Password-protected web dashboard with automatic snapshot refresh and low-frequency probing
