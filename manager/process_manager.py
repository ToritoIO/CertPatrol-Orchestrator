"""
Process manager for spawning and monitoring CertPatrol instances
"""
import os
import subprocess
import threading
import time
import signal
from typing import Dict, Optional
from datetime import datetime

from .config import CERTPATROL_CMD, MAX_CONCURRENT_SEARCHES
from .database import db
from .classifier import get_classifier


class SearchProcess:
    """Manages a single CertPatrol process"""
    
    def __init__(self, search_id: int, pattern: str, ct_logs: str = None,
                 batch_size: int = 256, poll_sleep: float = 3.0,
                 min_poll_sleep: float = 1.0, max_poll_sleep: float = 60.0,
                 max_memory_mb: int = 100, etld1: bool = False,
                 verbose: bool = False, quiet_warnings: bool = True,
                 quiet_parse_errors: bool = False, debug_all: bool = False,
                 checkpoint_prefix: str = None):
        self.search_id = search_id
        self.pattern = pattern
        self.ct_logs = ct_logs
        self.batch_size = batch_size
        self.poll_sleep = poll_sleep
        self.min_poll_sleep = min_poll_sleep
        self.max_poll_sleep = max_poll_sleep
        self.max_memory_mb = max_memory_mb
        self.etld1 = etld1
        self.verbose = verbose
        self.quiet_warnings = quiet_warnings
        self.quiet_parse_errors = quiet_parse_errors
        self.debug_all = debug_all
        self.checkpoint_prefix = checkpoint_prefix
        self.process = None
        self.thread = None
        self.running = False
        self.classifier = get_classifier()
    
    def start(self):
        """Start the CertPatrol process"""
        if self.running:
            return False
        
        # Build command with basic options
        cmd = [
            CERTPATROL_CMD,
            "-p", self.pattern,
            "-b", str(self.batch_size),
            "-s", str(self.poll_sleep),
            "-mn", str(self.min_poll_sleep),
            "-mx", str(self.max_poll_sleep),
            "-m", str(self.max_memory_mb)
        ]
        
        # Add checkpoint prefix
        if self.checkpoint_prefix:
            cmd.extend(["-c", self.checkpoint_prefix])
        else:
            cmd.extend(["-c", f"search_{self.search_id}"])
        
        # Add filtering options
        if self.etld1:
            cmd.append("-e")
        if self.verbose:
            cmd.append("-v")
        if self.quiet_warnings:
            cmd.append("-q")
        if self.quiet_parse_errors:
            cmd.append("-x")
        if self.debug_all:
            cmd.append("-d")
        
        # Add CT logs if specified
        if self.ct_logs:
            import json
            try:
                logs = json.loads(self.ct_logs)
                if logs:
                    cmd.extend(["-l"] + logs)
            except json.JSONDecodeError:
                pass
        
        try:
            # Start process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.running = True
            
            # Update database with PID
            db.update_search_status(self.search_id, "running", self.process.pid)
            
            # Start output reader thread
            self.thread = threading.Thread(target=self._read_output, daemon=True)
            self.thread.start()
            
            return True
        except Exception as e:
            db.update_search_status(self.search_id, "crashed")
            raise Exception(f"Failed to start process: {e}")
    
    def stop(self):
        """Stop the CertPatrol process gracefully"""
        if not self.running or not self.process:
            return False
        
        try:
            # Send SIGTERM for graceful shutdown
            self.process.send_signal(signal.SIGTERM)
            
            # Wait up to 10 seconds for graceful shutdown
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Force kill if not responding
                self.process.kill()
                self.process.wait()
            
            self.running = False
            db.update_search_status(self.search_id, "stopped", None)
            return True
        except Exception as e:
            raise Exception(f"Failed to stop process: {e}")
    
    def is_alive(self) -> bool:
        """Check if process is still running"""
        if not self.process:
            return False
        return self.process.poll() is None
    
    def _read_output(self):
        """Read stdout line by line and save to database"""
        try:
            for line in self.process.stdout:
                if not self.running:
                    break
                
                domain = line.strip()
                
                # Skip empty lines
                if not domain:
                    continue
                
                # Skip status messages (not domains)
                skip_patterns = [
                    'Checkpoints saved',
                    'Received SIGTERM',
                    'Graceful shutdown',
                    'shutdown',
                    'Tailing logs',
                    'Pattern:',
                    'Batch size:',
                    'initiating',
                ]
                
                # Check if line contains any skip pattern (case insensitive)
                if any(pattern.lower() in domain.lower() for pattern in skip_patterns):
                    continue
                
                # Basic domain validation: should contain at least one dot and no spaces
                if '.' not in domain or ' ' in domain:
                    continue
                
                classification = None
                try:
                    classification = self.classifier.classify(domain)
                except Exception as err:
                    print(f"Classification error for {domain}: {err}")

                # Save valid domain to database
                try:
                    db.add_result(
                        self.search_id,
                        domain,
                        score=classification.score if classification else None,
                        risk_level=classification.risk if classification else None,
                        matched_keyword=classification.matched_keyword if classification else None,
                        matched_tld=classification.matched_tld if classification else None,
                        classification=classification.to_record() if classification else None,
                    )
                except Exception as e:
                    print(f"Error saving result: {e}")
            
            # Process finished
            exit_code = self.process.wait()
            self.running = False
            
            if exit_code == 0:
                db.update_search_status(self.search_id, "stopped", None)
            else:
                db.update_search_status(self.search_id, "crashed", None)
        except Exception as e:
            print(f"Error reading process output: {e}")
            self.running = False
            db.update_search_status(self.search_id, "crashed", None)


class ProcessManager:
    """Manages multiple CertPatrol processes"""
    
    def __init__(self):
        self.processes: Dict[int, SearchProcess] = {}
        self.lock = threading.Lock()
    
    def start_search(self, search_id: int) -> bool:
        """Start a search process"""
        with self.lock:
            # Check if already running
            if search_id in self.processes and self.processes[search_id].is_alive():
                return False
            
            # Check concurrent limit
            active_count = sum(1 for p in self.processes.values() if p.is_alive())
            if active_count >= MAX_CONCURRENT_SEARCHES:
                raise Exception(f"Maximum concurrent searches ({MAX_CONCURRENT_SEARCHES}) reached")
            
            # Get search from database
            search = db.get_search(search_id)
            if not search:
                raise Exception(f"Search {search_id} not found")
            
            # Create and start process
            process = SearchProcess(
                search_id=search.id,
                pattern=search.pattern,
                ct_logs=search.ct_logs,
                batch_size=search.batch_size,
                poll_sleep=search.poll_sleep,
                min_poll_sleep=search.min_poll_sleep,
                max_poll_sleep=search.max_poll_sleep,
                max_memory_mb=search.max_memory_mb,
                etld1=bool(search.etld1),
                verbose=bool(search.verbose),
                quiet_warnings=bool(search.quiet_warnings),
                quiet_parse_errors=bool(search.quiet_parse_errors),
                debug_all=bool(search.debug_all),
                checkpoint_prefix=search.checkpoint_prefix
            )
            
            process.start()
            self.processes[search_id] = process
            return True
    
    def stop_search(self, search_id: int) -> bool:
        """Stop a search process"""
        with self.lock:
            if search_id not in self.processes:
                return False
            
            process = self.processes[search_id]
            result = process.stop()
            
            # Remove from active processes
            if not process.is_alive():
                del self.processes[search_id]
            
            return result
    
    def get_status(self, search_id: int) -> Optional[str]:
        """Get current status of a search"""
        with self.lock:
            if search_id in self.processes:
                process = self.processes[search_id]
                if process.is_alive():
                    return "running"
                else:
                    return "stopped"
            
            # Check database
            search = db.get_search(search_id)
            return search.status if search else None
    
    def list_active_searches(self) -> Dict[int, dict]:
        """List all active search processes"""
        with self.lock:
            active = {}
            for search_id, process in self.processes.items():
                if process.is_alive():
                    search = db.get_search(search_id)
                    if search:
                        active[search_id] = {
                            "name": search.name,
                            "pattern": search.pattern,
                            "pid": process.process.pid if process.process else None,
                            "status": "running"
                        }
            return active
    
    def cleanup_dead_processes(self):
        """Remove dead processes from tracking"""
        with self.lock:
            dead = [sid for sid, proc in self.processes.items() if not proc.is_alive()]
            for search_id in dead:
                del self.processes[search_id]
    
    def stop_all(self):
        """Stop all running processes"""
        with self.lock:
            for search_id in list(self.processes.keys()):
                try:
                    self.processes[search_id].stop()
                except Exception as e:
                    print(f"Error stopping search {search_id}: {e}")
            
            self.processes.clear()


# Global process manager instance
process_manager = ProcessManager()
