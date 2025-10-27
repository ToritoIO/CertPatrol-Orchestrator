# CertPatrol Orchestrator

Process orchestration platform for managing multiple [CertPatrol](https://github.com/ToritoIO/CertPatrol) instances with a modern web interface.

![CertPatrol Orchestrator](https://raw.githubusercontent.com/ToritoIO/CertPatrol-Orchestrator/main/manager/web/static/images/dashboard.png)

## Features

- **Process Orchestration**: Spawn and manage multiple CertPatrol instances in parallel
- **Project Management**: Organize searches into projects
- **Web UI**: Modern, responsive web interface for managing everything
- **Real-time Monitoring**: Live dashboard showing active searches and recent discoveries
- **Database Storage**: All results persistently stored in SQLite
- **CLI Interface**: Command-line tools for automation
- **Process Isolation**: Each search runs independently - crashes don't affect others

## Architecture

CertPatrol Orchestrator acts as a process orchestration platform that:
1. Spawns CertPatrol processes with different search patterns
2. Captures stdout from each process (one domain per line)
3. Stores results in a centralized database
4. Provides a web UI for management and monitoring

## Installation

Install the latest release from PyPI:

```bash
pip install certpatrol-orchestrator
```

Or install from source:

```bash
git clone https://github.com/ToritoIO/CertPatrol-Orchestrator.git
cd CertPatrol-Orchestrator
pip install -r requirements.txt
pip install -e .
```

## Quick Start

### 1. Initialize the database
```bash
certpatrol-orch init
```

### 2. Start the web server

```bash
certpatrol-orch server
# or pick a different port
# certpatrol-orch server --port 9090
```

Then open http://127.0.0.1:8080 in your browser.

**Note:** The server uses Waitress (production WSGI server) by default. Make sure it's installed:
```bash
pip install -r requirements.txt
```

### 3. Create a project and add searches via the Web UI

Or use the CLI:

```bash
# Create a project
certpatrol-orch add-project "Workers.dev Monitoring" -d "Monitor workers.dev domains"

# Add a search
certpatrol-orch add-search "Workers.dev Monitoring" "Workers Search" "workers\\.dev$"

# List searches to get the ID
certpatrol-orch list-searches

# Start the search
certpatrol-orch start <search_id>

# Check status
certpatrol-orch status
```

## CLI Commands

```bash
certpatrol-orch init                          # Initialize database
certpatrol-orch server [--port | -p]          # Start web server
certpatrol-orch add-project <name>            # Create project
certpatrol-orch list-projects                 # List all projects
certpatrol-orch add-search <project> <name> <pattern>  # Add search
certpatrol-orch list-searches [--project]     # List searches
certpatrol-orch start <search_id>             # Start search
certpatrol-orch stop <search_id>              # Stop search
certpatrol-orch status                        # Show all search statuses
```

## Web UI

The web interface provides:

- **Dashboard**: Overview of projects, active searches, and recent results
- **Projects**: Create, view, and delete projects
- **Searches**: Manage searches within projects (create, start, stop, delete)
- **Results**: View discovered domains with pagination

### Search Creation Options

When creating a search, you can configure:

- **Search Name**: Descriptive name for the search
- **Regex Pattern**: Regular expression to match domain names
- **Batch Size**: Number of entries to fetch per request (default: 256)
- **Poll Sleep**: Initial poll interval in seconds (default: 3.0)
- **Match base domains only (eTLD+1)**: Optional filter to match only base domains (e.g., example.co.uk instead of subdomain.example.co.uk)

All options include helpful tooltips. Advanced CertPatrol options are automatically configured with safe defaults to ensure proper output parsing and Orchestrator compatibility.

## Deployment

CertPatrol Orchestrator uses **Waitress**, a production-ready pure-Python WSGI server. This ensures:
- ✅ Multi-threaded request handling (4 concurrent requests by default)
- ✅ Stable and battle-tested
- ✅ Works on all platforms (Windows, macOS, Linux)
- ✅ No compilation required
- ✅ Suitable for both local and multi-user deployments

For advanced deployment scenarios (reverse proxies, load balancing, etc.), see the [Flask deployment documentation](https://flask.palletsprojects.com/en/stable/deploying/).

## Configuration

Environment variables:

- `MANAGER_HOST`: Web server host (default: 127.0.0.1)
- `MANAGER_PORT`: Web server port (default: 8080)
- `MANAGER_DEBUG`: Enable debug mode (default: False)
- `MAX_CONCURRENT_SEARCHES`: Max parallel searches (default: 10)

## Requirements

- Python 3.8+
- CertPatrol
- Flask 3.0+
- SQLAlchemy 2.0+

## Database Schema

**projects**: Project metadata
- id, name, description, created_at

**searches**: Search configurations
- id, project_id, name, pattern, ct_logs
- batch_size, poll_sleep, min_poll_sleep, max_poll_sleep, max_memory_mb
- etld1, verbose, quiet_warnings, quiet_parse_errors, debug_all
- checkpoint_prefix, status, pid, created_at

**results**: Discovered domains
- id, search_id, domain, discovered_at

## How It Works

1. Manager spawns CertPatrol as subprocess: `certpatrol -p <pattern> -c search_<id> -q`
2. Background thread reads stdout line-by-line
3. Each line (domain) is saved to database
4. Web UI queries database for display
5. Process status tracked in real-time

## API Endpoints

REST API available at `/api/*`:

- `GET /api/projects` - List projects
- `POST /api/projects` - Create project
- `GET /api/projects/<id>/searches` - List searches
- `POST /api/searches` - Create search
- `POST /api/searches/<id>/start` - Start search
- `POST /api/searches/<id>/stop` - Stop search
- `GET /api/searches/<id>/results` - Get results
- `GET /api/status` - System status

## License

MIT License — see [LICENSE](https://github.com/ToritoIO/CertPatrol-Orchestrator/blob/main/LICENSE) file for details.
