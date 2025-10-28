#!/usr/bin/env python3
"""
Command-line interface for CertPatrol Orchestrator
"""
import sys
import argparse
import json

from .config import HOST, PORT, DEBUG
from .database import db
from .process_manager import process_manager
from .app import run_server


def cmd_init(args):
    """Initialize the database"""
    print("Initializing database...")
    db.initialize()
    print(f"Database initialized at: {db.db_path}")
    return 0


def cmd_server(args):
    """Start the web server"""
    port = args.port
    print(f"Starting CertPatrol Orchestrator web server on {HOST}:{port}")
    print(f"Open http://{HOST}:{port} in your browser")
    run_server(port=port, debug=args.debug)
    return 0


def cmd_add_project(args):
    """Add a new project"""
    db.initialize()
    try:
        project = db.create_project(args.name, args.description)
        print(f"Project created: {project.name} (ID: {project.id})")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_list_projects(args):
    """List all projects"""
    db.initialize()
    projects = db.list_projects()
    
    if not projects:
        print("No projects found")
        return 0
    
    print(f"\nFound {len(projects)} project(s):\n")
    for project in projects:
        print(f"  [{project.id}] {project.name}")
        if project.description:
            print(f"      {project.description}")
        print(f"      Searches: {len(project.searches)}")
        print()
    return 0


def cmd_add_search(args):
    """Add a new search"""
    db.initialize()
    try:
        # Get project
        if args.project.isdigit():
            project = db.get_project(int(args.project))
        else:
            project = db.get_project_by_name(args.project)
        
        if not project:
            print(f"Error: Project '{args.project}' not found", file=sys.stderr)
            return 1
        
        # Parse CT logs if provided
        ct_logs = None
        if args.logs:
            ct_logs = json.dumps(args.logs)
        
        search = db.create_search(
            project_id=project.id,
            name=args.name,
            pattern=args.pattern,
            ct_logs=ct_logs,
            batch_size=args.batch,
            poll_sleep=args.sleep
        )
        print(f"Search created: {search.name} (ID: {search.id})")
        print(f"  Project: {project.name}")
        print(f"  Pattern: {search.pattern}")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_list_searches(args):
    """List all searches"""
    db.initialize()
    
    project_id = None
    if args.project:
        if args.project.isdigit():
            project_id = int(args.project)
        else:
            project = db.get_project_by_name(args.project)
            if project:
                project_id = project.id
    
    searches = db.list_searches(project_id)
    
    if not searches:
        print("No searches found")
        return 0
    
    print(f"\nFound {len(searches)} search(es):\n")
    for search in searches:
        project = db.get_project(search.project_id)
        print(f"  [{search.id}] {search.name}")
        print(f"      Project: {project.name if project else 'Unknown'}")
        print(f"      Pattern: {search.pattern}")
        print(f"      Status: {search.status}")
        print(f"      Results: {len(search.results)}")
        print()
    return 0


def cmd_start(args):
    """Start a search"""
    db.initialize()
    try:
        search = db.get_search(args.search_id)
        if not search:
            print(f"Error: Search {args.search_id} not found", file=sys.stderr)
            return 1
        
        print(f"Starting search: {search.name} (ID: {search.id})")
        process_manager.start_search(args.search_id)
        print("Search started successfully")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_stop(args):
    """Stop a search"""
    db.initialize()
    try:
        search = db.get_search(args.search_id)
        if not search:
            print(f"Error: Search {args.search_id} not found", file=sys.stderr)
            return 1
        
        print(f"Stopping search: {search.name} (ID: {search.id})")
        process_manager.stop_search(args.search_id)
        print("Search stopped successfully")
        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_status(args):
    """Show status of all searches"""
    db.initialize()
    
    active_searches = process_manager.list_active_searches()
    all_searches = db.list_searches()
    
    print(f"\nActive searches: {len(active_searches)}")
    if active_searches:
        print()
        for search_id, info in active_searches.items():
            print(f"  [{search_id}] {info['name']}")
            print(f"      Pattern: {info['pattern']}")
            print(f"      PID: {info['pid']}")
            print(f"      Status: {info['status']}")
            print()
    
    stopped_searches = [s for s in all_searches if s.status == 'stopped']
    if stopped_searches:
        print(f"Stopped searches: {len(stopped_searches)}")
        print()
        for search in stopped_searches:
            project = db.get_project(search.project_id)
            print(f"  [{search.id}] {search.name}")
            print(f"      Project: {project.name if project else 'Unknown'}")
            print(f"      Pattern: {search.pattern}")
            print()
    
    return 0


def main():
    """Main CLI entry point"""
    common_options = argparse.ArgumentParser(add_help=False)
    common_options.add_argument(
        '--database',
        '--db',
        '-f',
        dest='database',
        help=f'Path to the SQLite database file (default: {db.db_path})'
    )

    parser = argparse.ArgumentParser(
        description="CertPatrol Orchestrator - Process Orchestration for CertPatrol",
        parents=[common_options]
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # init command
    parser_init = subparsers.add_parser('init', help='Initialize database', parents=[common_options])
    parser_init.set_defaults(func=cmd_init)
    
    # server command
    parser_server = subparsers.add_parser('server', help='Start web server', parents=[common_options])
    parser_server.add_argument('--port', '-p', type=int, default=PORT, help=f'Port to bind to (default: {PORT})')
    parser_server.add_argument('--debug', action='store_true', default=DEBUG, help='Enable debug mode')
    parser_server.set_defaults(func=cmd_server)
    
    # add-project command
    parser_add_project = subparsers.add_parser('add-project', help='Create a new project', parents=[common_options])
    parser_add_project.add_argument('name', help='Project name')
    parser_add_project.add_argument('--description', '-d', help='Project description')
    parser_add_project.set_defaults(func=cmd_add_project)
    
    # list-projects command
    parser_list_projects = subparsers.add_parser('list-projects', help='List all projects', parents=[common_options])
    parser_list_projects.set_defaults(func=cmd_list_projects)
    
    # add-search command
    parser_add_search = subparsers.add_parser('add-search', help='Add a new search', parents=[common_options])
    parser_add_search.add_argument('project', help='Project name or ID')
    parser_add_search.add_argument('name', help='Search name')
    parser_add_search.add_argument('pattern', help='Regex pattern')
    parser_add_search.add_argument('--logs', '-l', nargs='+', help='CT logs to monitor')
    parser_add_search.add_argument('--batch', '-b', type=int, default=256, help='Batch size (default: 256)')
    parser_add_search.add_argument('--sleep', '-s', type=float, default=3.0, help='Poll sleep (default: 3.0)')
    parser_add_search.set_defaults(func=cmd_add_search)
    
    # list-searches command
    parser_list_searches = subparsers.add_parser('list-searches', help='List all searches', parents=[common_options])
    parser_list_searches.add_argument('--project', '-p', help='Filter by project name or ID')
    parser_list_searches.set_defaults(func=cmd_list_searches)
    
    # start command
    parser_start = subparsers.add_parser('start', help='Start a search', parents=[common_options])
    parser_start.add_argument('search_id', type=int, help='Search ID')
    parser_start.set_defaults(func=cmd_start)
    
    # stop command
    parser_stop = subparsers.add_parser('stop', help='Stop a search', parents=[common_options])
    parser_stop.add_argument('search_id', type=int, help='Search ID')
    parser_stop.set_defaults(func=cmd_stop)
    
    # status command
    parser_status = subparsers.add_parser('status', help='Show status of all searches', parents=[common_options])
    parser_status.set_defaults(func=cmd_status)
    
    args = parser.parse_args()
    
    if hasattr(args, 'database') and args.database:
        db.set_path(args.database)
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
