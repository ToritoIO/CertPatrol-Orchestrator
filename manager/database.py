"""
Database models and operations for CertPatrol Orchestrator
"""
import json
import os
from datetime import datetime
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, DateTime, ForeignKey, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, scoped_session, joinedload
from sqlalchemy.engine import Engine
from contextlib import contextmanager

from .config import DATABASE_PATH

Base = declarative_base()


# Enable WAL mode for SQLite to support concurrent reads/writes
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Project(Base):
    """Project model - groups multiple searches together"""
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    searches = relationship("Search", back_populates="project", cascade="all, delete-orphan")
    
    def to_dict(self):
        # Safely get search count (works even if object is detached)
        try:
            search_count = len(self.searches)
        except:
            search_count = 0
        
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "search_count": search_count
        }


class Search(Base):
    """Search model - represents a single certpatrol monitoring task"""
    __tablename__ = "searches"
    
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    pattern = Column(String(500), nullable=False)
    ct_logs = Column(Text)  # JSON array of log names
    
    # Performance options
    batch_size = Column(Integer, default=256)
    poll_sleep = Column(Float, default=3.0)
    min_poll_sleep = Column(Float, default=1.0)
    max_poll_sleep = Column(Float, default=60.0)
    max_memory_mb = Column(Integer, default=100)
    
    # Filtering options
    etld1 = Column(Integer, default=0)  # Boolean stored as int
    verbose = Column(Integer, default=0)  # Boolean stored as int
    quiet_warnings = Column(Integer, default=1)  # Boolean stored as int
    quiet_parse_errors = Column(Integer, default=0)  # Boolean stored as int
    debug_all = Column(Integer, default=0)  # Boolean stored as int
    
    # Checkpoint prefix
    checkpoint_prefix = Column(String(255))
    
    status = Column(String(50), default="stopped")  # stopped, running, crashed
    pid = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    project = relationship("Project", back_populates="searches")
    results = relationship("Result", back_populates="search", cascade="all, delete-orphan")
    
    def to_dict(self):
        # Safely get result count (works even if object is detached)
        try:
            result_count = len(self.results)
        except:
            result_count = 0

        if self.ct_logs:
            try:
                ct_logs = json.loads(self.ct_logs)
            except (TypeError, ValueError):
                ct_logs = self.ct_logs
        else:
            ct_logs = None

        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "pattern": self.pattern,
            "ct_logs": ct_logs,
            "batch_size": self.batch_size,
            "poll_sleep": self.poll_sleep,
            "min_poll_sleep": self.min_poll_sleep,
            "max_poll_sleep": self.max_poll_sleep,
            "max_memory_mb": self.max_memory_mb,
            "etld1": bool(self.etld1),
            "verbose": bool(self.verbose),
            "quiet_warnings": bool(self.quiet_warnings),
            "quiet_parse_errors": bool(self.quiet_parse_errors),
            "debug_all": bool(self.debug_all),
            "checkpoint_prefix": self.checkpoint_prefix,
            "status": self.status,
            "pid": self.pid,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "result_count": result_count
        }


class Result(Base):
    """Result model - stores discovered domains"""
    __tablename__ = "results"
    
    id = Column(Integer, primary_key=True)
    search_id = Column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=False)
    domain = Column(String(500), nullable=False)
    discovered_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    search = relationship("Search", back_populates="results")
    
    def to_dict(self):
        # Try to get search name from various sources
        search_name = None
        
        # First check if we stored it manually
        if hasattr(self, '_search_name'):
            search_name = self._search_name
        else:
            # Try to get it from relationship if still attached
            try:
                search_name = self.search.name if self.search else None
            except:
                pass
        
        result = {
            "id": self.id,
            "search_id": self.search_id,
            "domain": self.domain,
            "discovered_at": self.discovered_at.isoformat() if self.discovered_at else None
        }
        
        if search_name:
            result["search_name"] = search_name
        
        return result


class Database:
    """Database manager with connection pooling and session management"""
    
    def __init__(self, db_path: str = None):
        self.db_path = os.path.abspath(db_path) if db_path else DATABASE_PATH
        self.engine = None
        self.session_factory = None
        self.Session = None
    
    def set_path(self, db_path: str):
        """Override database path and reset existing connections"""
        new_path = os.path.abspath(db_path)
        if new_path == self.db_path:
            return
        self.db_path = new_path
        if self.engine:
            self.engine.dispose()
            self.engine = None
        self.session_factory = None
        self.Session = None
    
    def initialize(self):
        """Initialize database connection and create tables"""
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        # Create engine
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False}
        )
        
        # Create tables
        Base.metadata.create_all(self.engine)
        
        # Create session factory
        self.session_factory = sessionmaker(bind=self.engine)
        self.Session = scoped_session(self.session_factory)
    
    @contextmanager
    def session_scope(self):
        """Provide a transactional scope for database operations"""
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    # Project operations
    def create_project(self, name: str, description: str = None) -> Project:
        """Create a new project"""
        with self.session_scope() as session:
            project = Project(name=name, description=description)
            session.add(project)
            session.flush()
            session.refresh(project)
            # Force load the searches relationship before expunging
            _ = len(project.searches)
            # Detach from session before returning
            session.expunge(project)
            return project
    
    def get_project(self, project_id: int) -> Optional[Project]:
        """Get project by ID"""
        with self.session_scope() as session:
            project = session.query(Project).filter_by(id=project_id).first()
            if project:
                # Force load relationships before detaching
                _ = len(project.searches)
                session.expunge(project)
            return project
    
    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get project by name"""
        with self.session_scope() as session:
            project = session.query(Project).filter_by(name=name).first()
            if project:
                # Force load relationships before detaching
                _ = len(project.searches)
                session.expunge(project)
            return project
    
    def list_projects(self) -> List[Project]:
        """List all projects"""
        with self.session_scope() as session:
            projects = session.query(Project).order_by(Project.created_at.desc()).all()
            # Force load relationships before expunging
            for project in projects:
                _ = len(project.searches)
                session.expunge(project)
            return projects
    
    def update_project(self, project_id: int, name: str = None, description: str = None) -> Optional[Project]:
        """Update project details"""
        with self.session_scope() as session:
            project = session.query(Project).filter_by(id=project_id).first()
            if project:
                if name is not None:
                    project.name = name
                if description is not None:
                    project.description = description
                session.flush()  # Ensure changes are written before expunge
                session.expunge(project)
            return project
    
    def delete_project(self, project_id: int) -> bool:
        """Delete project and all associated searches and results"""
        with self.session_scope() as session:
            project = session.query(Project).filter_by(id=project_id).first()
            if project:
                session.delete(project)
                return True
            return False
    
    # Search operations
    def create_search(self, project_id: int, name: str, pattern: str, 
                     ct_logs: str = None, batch_size: int = 256, 
                     poll_sleep: float = 3.0, min_poll_sleep: float = 1.0,
                     max_poll_sleep: float = 60.0, max_memory_mb: int = 100,
                     etld1: bool = False, verbose: bool = False,
                     quiet_warnings: bool = True, quiet_parse_errors: bool = False,
                     debug_all: bool = False, checkpoint_prefix: str = None) -> Search:
        """Create a new search"""
        with self.session_scope() as session:
            search = Search(
                project_id=project_id,
                name=name,
                pattern=pattern,
                ct_logs=ct_logs,
                batch_size=batch_size,
                poll_sleep=poll_sleep,
                min_poll_sleep=min_poll_sleep,
                max_poll_sleep=max_poll_sleep,
                max_memory_mb=max_memory_mb,
                etld1=int(etld1),
                verbose=int(verbose),
                quiet_warnings=int(quiet_warnings),
                quiet_parse_errors=int(quiet_parse_errors),
                debug_all=int(debug_all),
                checkpoint_prefix=checkpoint_prefix
            )
            session.add(search)
            session.flush()
            session.refresh(search)
            # Force load the results relationship before expunging
            _ = len(search.results)
            # Detach from session before returning
            session.expunge(search)
            return search
    
    def get_search(self, search_id: int) -> Optional[Search]:
        """Get search by ID"""
        with self.session_scope() as session:
            search = session.query(Search).filter_by(id=search_id).first()
            if search:
                # Force load relationships before detaching
                _ = len(search.results)
                session.expunge(search)
            return search
    
    def list_searches(self, project_id: int = None) -> List[Search]:
        """List all searches, optionally filtered by project"""
        with self.session_scope() as session:
            query = session.query(Search)
            if project_id:
                query = query.filter_by(project_id=project_id)
            searches = query.order_by(Search.created_at.desc()).all()
            # Force load relationships before expunging
            for search in searches:
                _ = len(search.results)
                session.expunge(search)
            return searches

    def update_search(self, search_id: int, **fields) -> Optional[Search]:
        """Update search configuration values"""
        with self.session_scope() as session:
            search = session.query(Search).filter_by(id=search_id).first()
            if not search:
                return None

            boolean_fields = {"etld1", "verbose", "quiet_warnings", "quiet_parse_errors", "debug_all"}

            for key, value in fields.items():
                if not hasattr(search, key):
                    continue
                if key in boolean_fields and value is not None:
                    setattr(search, key, int(value))
                else:
                    setattr(search, key, value)

            session.flush()
            session.refresh(search)
            _ = len(search.results)
            session.expunge(search)
            return search

    def update_search_status(self, search_id: int, status: str, pid: int = None):
        """Update search status and PID"""
        with self.session_scope() as session:
            search = session.query(Search).filter_by(id=search_id).first()
            if search:
                search.status = status
                if pid is not None:
                    search.pid = pid
    
    def delete_search(self, search_id: int) -> bool:
        """Delete search and all associated results"""
        with self.session_scope() as session:
            search = session.query(Search).filter_by(id=search_id).first()
            if search:
                session.delete(search)
                return True
            return False
    
    # Result operations
    def add_result(self, search_id: int, domain: str):
        """Add a new result (discovered domain)"""
        with self.session_scope() as session:
            result = Result(search_id=search_id, domain=domain)
            session.add(result)
    
    def get_results(self, search_id: int, limit: int = 100, offset: int = 0) -> List[Result]:
        """Get results for a search with pagination"""
        with self.session_scope() as session:
            results = (session.query(Result)
                      .filter_by(search_id=search_id)
                      .order_by(Result.discovered_at.desc())
                      .limit(limit)
                      .offset(offset)
                      .all())
            for result in results:
                session.expunge(result)
            return results
    
    def count_results(self, search_id: int) -> int:
        """Count total results for a search"""
        with self.session_scope() as session:
            return session.query(Result).filter_by(search_id=search_id).count()
    
    def get_recent_results(self, limit: int = 50) -> List[Result]:
        """Get most recent results across all searches"""
        with self.session_scope() as session:
            results = (session.query(Result)
                      .options(joinedload(Result.search))
                      .order_by(Result.discovered_at.desc())
                      .limit(limit)
                      .all())
            for result in results:
                # Manually store search name before expunging
                if result.search:
                    result._search_name = result.search.name
                else:
                    result._search_name = None
                session.expunge(result)
            return results
    
    def get_discoveries_by_day(self, start_date: str, end_date: str) -> dict:
        """Get discoveries grouped by day and project"""
        with self.session_scope() as session:
            from sqlalchemy import func
            
            # Query results with date grouping
            query = (session.query(
                func.date(Result.discovered_at).label('date'),
                Search.project_id,
                func.count(Result.id).label('count')
            )
            .join(Search, Result.search_id == Search.id)
            .filter(
                func.date(Result.discovered_at) >= start_date,
                func.date(Result.discovered_at) <= end_date
            )
            .group_by(func.date(Result.discovered_at), Search.project_id)
            .order_by(func.date(Result.discovered_at))
            .all())
            
            # Get project names
            projects = session.query(Project).all()
            project_map = {p.id: p.name for p in projects}
            
            return {
                'results': query,
                'project_map': project_map
            }


# Global database instance
db = Database()
