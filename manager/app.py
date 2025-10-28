"""
Flask web application with REST API for CertPatrol Orchestrator
"""
from flask import Flask, render_template, request, jsonify
import os
import json
import signal
import sys
import atexit
from datetime import datetime

from .config import SECRET_KEY, HOST, PORT, DEBUG
from .database import db, Project, Search, Result
from .process_manager import process_manager

# Initialize Flask app
package_root = os.path.dirname(__file__)
app = Flask(
    __name__,
    template_folder=os.path.join(package_root, 'web', 'templates'),
    static_folder=os.path.join(package_root, 'web', 'static'),
)
app.config['SECRET_KEY'] = SECRET_KEY


# Database initialization will happen in run_server()


# Web UI Routes
@app.route('/')
def dashboard():
    """Dashboard page"""
    return render_template('dashboard.html')


@app.route('/projects')
def projects_page():
    """Projects management page"""
    return render_template('projects.html')


@app.route('/projects/<int:project_id>/searches')
def searches_page(project_id):
    """Searches management page"""
    project = db.get_project(project_id)
    if not project:
        return "Project not found", 404
    return render_template('searches.html', project=project)


@app.route('/searches/<int:search_id>/results')
def results_page(search_id):
    """Results viewer page"""
    search = db.get_search(search_id)
    if not search:
        return "Search not found", 404
    return render_template('results.html', search=search)


# API Routes - Projects
@app.route('/api/projects', methods=['GET'])
def list_projects():
    """List all projects"""
    try:
        projects = db.list_projects()
        return jsonify([p.to_dict() for p in projects])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects', methods=['POST'])
def create_project():
    """Create a new project"""
    try:
        data = request.get_json()
        name = data.get('name')
        description = data.get('description', '')
        
        if not name:
            return jsonify({"error": "Name is required"}), 400
        
        project = db.create_project(name, description)
        return jsonify(project.to_dict()), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['GET'])
def get_project(project_id):
    """Get project details"""
    try:
        project = db.get_project(project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        return jsonify(project.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['PUT'])
def update_project(project_id):
    """Update a project"""
    try:
        data = request.get_json()
        name = data.get('name')
        description = data.get('description')
        
        project = db.update_project(project_id, name, description)
        if project:
            return jsonify(project.to_dict()), 200
        return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/projects/<int:project_id>', methods=['DELETE'])
def delete_project(project_id):
    """Delete a project"""
    try:
        # Stop all searches in this project first
        searches = db.list_searches(project_id)
        for search in searches:
            try:
                process_manager.stop_search(search.id)
            except:
                pass
        
        if db.delete_project(project_id):
            return jsonify({"message": "Project deleted"}), 200
        return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# API Routes - Searches
@app.route('/api/projects/<int:project_id>/searches', methods=['GET'])
def list_project_searches(project_id):
    """List all searches in a project"""
    try:
        searches = db.list_searches(project_id)
        return jsonify([s.to_dict() for s in searches])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/searches', methods=['POST'])
def create_search():
    """Create a new search"""
    try:
        data = request.get_json()
        project_id = data.get('project_id')
        name = data.get('name')
        pattern = data.get('pattern')
        ct_logs = data.get('ct_logs')  # JSON array or None
        
        # Basic options
        batch_size = data.get('batch_size', 256)
        poll_sleep = data.get('poll_sleep', 3.0)
        
        # Advanced performance options
        min_poll_sleep = data.get('min_poll_sleep', 1.0)
        max_poll_sleep = data.get('max_poll_sleep', 60.0)
        max_memory_mb = data.get('max_memory_mb', 100)
        
        # Filtering options
        etld1 = data.get('etld1', False)
        verbose = data.get('verbose', False)
        quiet_warnings = data.get('quiet_warnings', True)
        quiet_parse_errors = data.get('quiet_parse_errors', False)
        debug_all = data.get('debug_all', False)
        
        # Checkpoint prefix
        checkpoint_prefix = data.get('checkpoint_prefix')
        
        if not project_id or not name or not pattern:
            return jsonify({"error": "project_id, name, and pattern are required"}), 400
        
        # Convert ct_logs list to JSON string if provided
        if ct_logs:
            ct_logs = json.dumps(ct_logs)
        
        search = db.create_search(
            project_id=project_id,
            name=name,
            pattern=pattern,
            ct_logs=ct_logs,
            batch_size=batch_size,
            poll_sleep=poll_sleep,
            min_poll_sleep=min_poll_sleep,
            max_poll_sleep=max_poll_sleep,
            max_memory_mb=max_memory_mb,
            etld1=etld1,
            verbose=verbose,
            quiet_warnings=quiet_warnings,
            quiet_parse_errors=quiet_parse_errors,
            debug_all=debug_all,
            checkpoint_prefix=checkpoint_prefix
        )
        return jsonify(search.to_dict()), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/searches/<int:search_id>', methods=['GET'])
def get_search(search_id):
    """Get search details"""
    try:
        search = db.get_search(search_id)
        if not search:
            return jsonify({"error": "Search not found"}), 404
        return jsonify(search.to_dict())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/searches/<int:search_id>', methods=['PUT'])
def update_search(search_id):
    """Update search configuration"""
    try:
        data = request.get_json() or {}
        update_fields = {}

        def coerce_int(key):
            value = data.get(key)
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer")

        def coerce_float(key):
            value = data.get(key)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a number")

        def coerce_bool(value, key):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ('true', '1', 'yes', 'on'):
                    return True
                if lowered in ('false', '0', 'no', 'off'):
                    return False
            raise ValueError(f"{key} must be a boolean")

        if 'name' in data:
            name = data.get('name')
            if not name:
                return jsonify({"error": "Name cannot be empty"}), 400
            update_fields['name'] = name

        if 'pattern' in data:
            pattern = data.get('pattern')
            if not pattern:
                return jsonify({"error": "Pattern cannot be empty"}), 400
            update_fields['pattern'] = pattern

        if 'ct_logs' in data:
            ct_logs = data.get('ct_logs')
            if isinstance(ct_logs, list):
                update_fields['ct_logs'] = json.dumps(ct_logs) if ct_logs else None
            elif ct_logs is None:
                update_fields['ct_logs'] = None
            else:
                return jsonify({"error": "ct_logs must be a list or null"}), 400

        for key in ['batch_size', 'max_memory_mb']:
            if key in data:
                update_fields[key] = coerce_int(key)

        for key in ['poll_sleep', 'min_poll_sleep', 'max_poll_sleep']:
            if key in data:
                update_fields[key] = coerce_float(key)

        for key in ['etld1', 'verbose', 'quiet_warnings', 'quiet_parse_errors', 'debug_all']:
            if key in data:
                update_fields[key] = coerce_bool(data.get(key), key)

        if 'checkpoint_prefix' in data:
            update_fields['checkpoint_prefix'] = data.get('checkpoint_prefix')

        if not update_fields:
            return jsonify({"error": "No fields provided"}), 400

        search = db.update_search(search_id, **update_fields)
        if not search:
            return jsonify({"error": "Search not found"}), 404

        return jsonify(search.to_dict()), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/searches/<int:search_id>', methods=['DELETE'])
def delete_search(search_id):
    """Delete a search"""
    try:
        # Stop the search first
        try:
            process_manager.stop_search(search_id)
        except:
            pass
        
        if db.delete_search(search_id):
            return jsonify({"message": "Search deleted"}), 200
        return jsonify({"error": "Search not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# API Routes - Process Control
@app.route('/api/searches/<int:search_id>/start', methods=['POST'])
def start_search(search_id):
    """Start a search process"""
    try:
        process_manager.start_search(search_id)
        return jsonify({"message": "Search started", "status": "running"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/searches/<int:search_id>/stop', methods=['POST'])
def stop_search(search_id):
    """Stop a search process"""
    try:
        import os
        import signal
        
        # Get search from database
        search = db.get_search(search_id)
        if not search:
            return jsonify({"error": "Search not found"}), 404
        
        # Try to stop via process manager first
        try:
            process_manager.stop_search(search_id)
        except:
            pass  # Process not tracked, handle manually
        
        # If there's a PID, try to kill the process directly
        if search.pid:
            try:
                os.kill(search.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass  # Process already dead
            except Exception as e:
                print(f"Error killing process {search.pid}: {e}")
        
        # Always update database status to stopped
        db.update_search_status(search_id, "stopped", None)
        
        return jsonify({"message": "Search stopped", "status": "stopped"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/searches/<int:search_id>/status', methods=['GET'])
def get_search_status(search_id):
    """Get current status of a search"""
    try:
        status = process_manager.get_status(search_id)
        if status is None:
            return jsonify({"error": "Search not found"}), 404
        return jsonify({"search_id": search_id, "status": status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# API Routes - Results
@app.route('/api/searches/<int:search_id>/results', methods=['GET'])
def get_search_results(search_id):
    """Get results for a search with pagination"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        min_score = request.args.get('min_score', type=int)
        risk = request.args.get('risk')
        if risk:
            risk = risk.lower()
        
        results = db.get_results(
            search_id,
            limit,
            offset,
            min_score=min_score,
            risk=risk,
        )
        total = db.count_results(search_id, min_score=min_score, risk=risk)
        
        return jsonify({
            "results": [r.to_dict() for r in results],
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": {
                "min_score": min_score,
                "risk": risk,
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/results/recent', methods=['GET'])
def get_recent_results():
    """Get most recent results across all searches"""
    try:
        limit = request.args.get('limit', 50, type=int)
        results = db.get_recent_results(limit)
        return jsonify([r.to_dict() for r in results])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/results/total', methods=['GET'])
def get_total_results():
    """Get total count of all results across all searches"""
    try:
        with db.session_scope() as session:
            from .database import Result
            total = session.query(Result).count()
        return jsonify({"total": total})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/results/chart', methods=['GET'])
def get_chart_data():
    """Get discoveries grouped by day for chart"""
    try:
        from datetime import datetime, timedelta
        
        # Get date range from query params
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Default to last 30 days if not provided
        if not end_date:
            end_date = datetime.now().date()
        else:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
        if not start_date:
            start_date = end_date - timedelta(days=30)
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        
        # Get data from database
        data = db.get_discoveries_by_day(start_date.isoformat(), end_date.isoformat())
        
        # Generate all dates in range
        date_range = []
        current = start_date
        while current <= end_date:
            date_range.append(current.isoformat())
            current += timedelta(days=1)
        
        # Organize data by project
        project_data = {}
        for row in data['results']:
            project_id = row.project_id
            if project_id not in project_data:
                project_data[project_id] = {}
            project_data[project_id][str(row.date)] = row.count
        
        # Build response
        projects = []
        for project_id, counts in project_data.items():
            project_name = data['project_map'].get(project_id, f'Project {project_id}')
            # Fill in missing dates with 0
            daily_counts = [counts.get(date, 0) for date in date_range]
            projects.append({
                'id': project_id,
                'name': project_name,
                'data': daily_counts
            })
        
        # Format dates for display
        formatted_dates = [datetime.strptime(d, '%Y-%m-%d').strftime('%b %d') for d in date_range]
        
        return jsonify({
            'dates': formatted_dates,
            'projects': projects
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# API Routes - Status & Stats
@app.route('/api/status', methods=['GET'])
def get_status():
    """Get overall system status"""
    try:
        projects = db.list_projects()
        
        # Get running searches from database (more reliable than in-memory tracking)
        all_searches = db.list_searches()
        running_searches = [s for s in all_searches if s.status == 'running']
        
        # Build active search details
        active_search_details = {}
        for search in running_searches:
            active_search_details[search.id] = {
                "name": search.name,
                "pattern": search.pattern,
                "pid": search.pid,
                "status": "running"
            }
        
        # Clean up dead processes
        process_manager.cleanup_dead_processes()
        
        return jsonify({
            "total_projects": len(projects),
            "active_searches": len(running_searches),
            "active_search_details": active_search_details
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ct-logs', methods=['GET'])
def get_ct_logs():
    """Get available CT logs grouped by provider"""
    try:
        import requests
        
        # Fetch logs from Google's official list
        resp = requests.get("https://www.gstatic.com/ct/log_list/v3/all_logs_list.json", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        logs_by_provider = {}
        
        # Extract logs from all operators
        for operator in data.get("operators", []):
            provider_name = operator.get("name", "Unknown")
            
            for log in operator.get("logs", []):
                # Check if log is usable/qualified
                state = log.get("state", {})
                if "usable" in state or "qualified" in state:
                    description = log.get("description", "")
                    
                    # Generate clean log name from description
                    name = description.lower()
                    name = name.replace("'", "").replace('"', '')
                    name = ''.join(c if c.isalnum() or c in [' ', '-'] else ' ' for c in name)
                    name = '_'.join(name.split())
                    
                    if not name:
                        name = log.get("log_id", "unknown")[:16]
                    
                    if provider_name not in logs_by_provider:
                        logs_by_provider[provider_name] = []
                    
                    logs_by_provider[provider_name].append({
                        "name": name,
                        "description": description,
                        "url": log.get("url", "")
                    })
        
        return jsonify(logs_by_provider)
        
    except Exception as e:
        # Return empty dict on error - UI will show "All logs" option
        return jsonify({}), 200


def cleanup_on_exit():
    """Cleanup function to stop all processes when server shuts down"""
    print("\nShutting down CertPatrol Orchestrator...")
    try:
        process_manager.stop_all()
        print("All search processes stopped.")
    except Exception as e:
        print(f"Error during cleanup: {e}")


def signal_handler(sig, frame):
    """Handle termination signals"""
    print(f"\nReceived signal {sig}")
    cleanup_on_exit()
    sys.exit(0)


def run_server(host: str = None, port: int = None, debug: bool = None):
    """Run the server with Waitress production WSGI server
    
    Args:
        host: Host to bind to (default from config)
        port: Port to bind to (default from config)
        debug: Enable debug mode (default from config, unused with Waitress)
    """
    # Register cleanup handlers
    atexit.register(cleanup_on_exit)
    signal.signal(signal.SIGINT, signal_handler)   # Handle Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Handle kill command
    
    host = host or HOST
    port = port or PORT
    
    # Initialize database
    db.initialize()
    
    # Import Waitress
    try:
        from waitress import serve
    except ImportError:
        print("ERROR: Waitress is not installed.")
        print("Install it with: pip install waitress")
        print("\nOr install all requirements: pip install -r requirements.txt")
        sys.exit(1)
    
    print("Starting CertPatrol Orchestrator...")
    print(f"Server running on http://{host}:{port}")
    print("Press Ctrl+C to stop")
    print()
    
    # Run with Waitress (production-ready WSGI server)
    # threads=4 means it can handle 4 concurrent requests
    serve(app, host=host, port=port, threads=4, url_scheme='http')


if __name__ == '__main__':
    run_server()
