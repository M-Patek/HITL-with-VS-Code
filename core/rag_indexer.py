import os
import logging
from typing import List, Dict
import pathspec

logger = logging.getLogger(__name__)

class WorkspaceIndexer:
    """
    Indexes the workspace files for RAG (Retrieval Augmented Generation).
    """
    def __init__(self, embedding_model=None):
        self.embedding_model = embedding_model
        # [Fix] Default ignore list now includes hidden directories
        self.default_ignore_dirs = {
            'node_modules', 'venv', '__pycache__', '.git', '.vscode', '.idea', 'dist', 'build'
        }
        self.default_ignore_files = {
            'package-lock.json', 'yarn.lock', '.DS_Store', '.env'
        }

    def _load_gitignore(self, root_path: str) -> pathspec.PathSpec:
        gitignore_path = os.path.join(root_path, ".gitignore")
        lines = []
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        return pathspec.PathSpec.from_lines('gitwildmatch', lines)

    def _index_workspace_sync(self, root_path: str) -> List[Dict[str, str]]:
        documents = []
        global_spec = self._load_gitignore(root_path)
        
        for root, dirs, files in os.walk(root_path):
            # [Fix] Security: Skip hidden directories (starting with .)
            # This prevents indexing .git internals, .env folders, etc.
            dirs[:] = [d for d in dirs if d not in self.default_ignore_dirs and not d.startswith('.')]
            
            for file in files:
                # [Fix] Security: Skip hidden files (starting with .)
                if file.startswith('.') or file in self.default_ignore_files:
                    continue

                file_path = os.path.join(root, file)
                
                # [Fix] Security: Explicitly check for Symlinks
                # Prevents arbitrary file read if a symlink points outside the workspace (e.g., to /etc/passwd)
                if os.path.islink(file_path):
                    logger.debug(f"Skipping symlink: {file_path}")
                    continue

                rel_path = os.path.relpath(file_path, root_path)
                
                if global_spec.match_file(rel_path):
                    continue
                
                try:
                    # Basic binary check
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                    # Simple heuristic to skip large files or minified code
                    if len(content) > 100000: # 100KB limit
                        continue

                    documents.append({
                        "path": rel_path,
                        "content": content
                    })
                except UnicodeDecodeError:
                    pass # Skip binary files
                except Exception as e:
                    logger.warning(f"Failed to index {file_path}: {e}")
                    
        return documents

    def index(self, root_path: str):
        logger.info(f"Indexing workspace: {root_path}")
        docs = self._index_workspace_sync(root_path)
        # In a real impl, we would chunk docs and generate embeddings here.
        logger.info(f"Indexed {len(docs)} documents.")
        return docs
